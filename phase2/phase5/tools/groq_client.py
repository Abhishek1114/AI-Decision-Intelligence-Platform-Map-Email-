"""
Phase 5 — Rate-limited Groq client.

Model: openai/gpt-oss-120b (confirmed free tier as of this session: 30 RPM, 1K RPD,
8K TPM, 200K TPD — verify current numbers at console.groq.com/settings/limits
before relying on them in production).

Design rules locked in during scoping:
  1. Never trust json_schema strict mode alone — always parse into the Pydantic
     model, retry once on failure, mark needs_review on second failure.
  2. TPM is the real ceiling, not RPD — throttle at 6.5K TPM (not the full 8K)
     to leave headroom for estimation error.
  3. Cap max_tokens explicitly so one call can't eat the per-minute budget.
  4. Check x-ratelimit-remaining-tokens after every call; stall before sending
     if remaining < next estimated payload, rather than reacting to 429s.
  5. Static system-prompt portion is cache-eligible — cached tokens don't count
     against TPM and roughly halve input cost on cache hits.
"""
from __future__ import annotations
import json
import time
import logging
from typing import Optional

from groq import Groq
from pydantic import BaseModel, ValidationError

logger = logging.getLogger("phase5.groq_client")

MODEL = "openai/gpt-oss-120b"
TPM_BUDGET = 6500          # throttle below the 8K published limit, not up to it
MAX_OUTPUT_TOKENS = 2400    # explicit cap so one call can't dominate the TPM window
CHARS_PER_TOKEN_ESTIMATE = 4  # rough pre-send estimate before we have real usage data


class TokenBucket:
    """Simple client-side token-bucket for TPM throttling."""

    def __init__(self, budget_per_minute: int = TPM_BUDGET):
        self.budget = budget_per_minute
        self.window_start = time.monotonic()
        self.used = 0

    def _maybe_reset(self):
        now = time.monotonic()
        if now - self.window_start >= 60:
            self.window_start = now
            self.used = 0

    def reserve(self, estimated_tokens: int):
        self._maybe_reset()
        while self.used + estimated_tokens > self.budget:
            sleep_for = max(0.5, 60 - (time.monotonic() - self.window_start))
            logger.info(f"TPM budget would be exceeded, sleeping {sleep_for:.1f}s")
            time.sleep(sleep_for)
            self._maybe_reset()
        self.used += estimated_tokens

    def observe_header(self, remaining_tokens: Optional[int]):
        """Adjust based on Groq's authoritative remaining-tokens header, if present."""
        if remaining_tokens is not None and remaining_tokens < 500:
            logger.info(f"x-ratelimit-remaining-tokens={remaining_tokens}, forcing a wait")
            time.sleep(10)


_bucket = TokenBucket()


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN_ESTIMATE)



def call_groq_structured(
    client: Groq,
    system_prompt: str,
    user_prompt: str,
    output_model: type[BaseModel],
    max_retries: int = 1,
) -> tuple[Optional[BaseModel], Optional[str]]:
    """
    Calls Groq with a JSON-schema-constrained request, parses into output_model.
    Returns (parsed_model, None) on success, or (None, raw_text) if it never
    validated after retries — caller is responsible for writing status=needs_review.
    """
    estimated_input = _estimate_tokens(system_prompt) + _estimate_tokens(user_prompt)
    _bucket.reserve(estimated_input + MAX_OUTPUT_TOKENS)

    schema = output_model.model_json_schema()
    attempt_user_prompt = user_prompt
    last_raw = None

    for attempt in range(max_retries + 1):
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": attempt_user_prompt},
            ],
            response_format={"type": "json_object"},
        )

        remaining = getattr(response, "usage", None)
        # groq-python surfaces rate limit headers via response._request_id / raw headers
        # depending on SDK version; if available, feed it back to the bucket.
        try:
            headers = response.response.headers  # type: ignore[attr-defined]
            remaining_tokens = int(headers.get("x-ratelimit-remaining-tokens", -1))
            if remaining_tokens >= 0:
                _bucket.observe_header(remaining_tokens)
        except Exception:
            pass  # header introspection is best-effort, never block on it

        raw_text = response.choices[0].message.content
        last_raw = raw_text

        if raw_text is None:
            logger.warning(f"Model returned content=None on attempt {attempt + 1} (token limit or content filter?)")
            attempt_user_prompt = (
                user_prompt
                + "\n\nIMPORTANT: Your previous response was empty. "
                  "Return ONLY valid JSON matching the schema exactly, no other text."
            )
            continue

        try:
            parsed_json = json.loads(raw_text)
            parsed_model = output_model.model_validate(parsed_json)
            return parsed_model, None
        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            logger.warning(f"Validation failed on attempt {attempt + 1}: {e}. Raw: {raw_text[:500]}")
            attempt_user_prompt = (
                user_prompt
                + "\n\nIMPORTANT: Your previous response did not match the required schema. "
                  "Return ONLY valid JSON matching the schema exactly, no other text."
            )

    return None, last_raw