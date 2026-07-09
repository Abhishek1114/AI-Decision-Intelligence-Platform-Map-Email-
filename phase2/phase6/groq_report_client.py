"""
Phase 6 — groq_report_client.py

Model: openai/gpt-oss-120b (matches Phase 5, per project decision).

Deliberately reuses Phase 5's token-bucket throttle rather than
standing up a second rate limiter. On Groq's free tier, rate limits are
enforced at the org level, so Phase 6's calls share the same TPM/RPD
pool as Phase 5's live consumer regardless of whether they share code —
importing the same throttle instance at least keeps both consumers
honest about the same budget instead of each independently guessing
at remaining headroom.

ASSUMPTION FLAGGED: this imports TokenBucketThrottle from
phase2.phase5.rate_limiter, matching the interface referenced in the
Phase 5 handoff (client-side throttling against x-ratelimit-remaining-
tokens). If Phase 5's actual module name/interface differs, update the
import below — the rest of this file only depends on `wait_if_needed()`
and `record_usage(response.usage)` existing on that object.
"""

import json
import time

from groq import Groq

from phase2.phase5.rate_limiter import TokenBucketThrottle

MODEL = "openai/gpt-oss-120b"

client = Groq()
# Same class, same defaults as Phase 5's consumer — both share the same
# org-level Groq quota, so both should throttle against the same numbers.
throttle = TokenBucketThrottle(model=MODEL)


def generate_report_text(system_prompt: str, user_payload: dict, max_retries: int = 1) -> str:
    """
    Single call, no built-in retry loop here — retry-on-validation-failure
    is handled one level up in generate_report.py, since only that layer
    knows whether the failure was a citation/structure problem worth
    retrying with a tightened prompt, vs. a transport error worth a
    plain retry.
    """
    throttle.wait_if_needed()

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload)},
                ],
            )
            throttle.record_usage(response.usage)
            return response.choices[0].message.content

        except Exception as exc:
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            raise