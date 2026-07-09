"""
Phase 5 — rate_limiter.py

This module did not exist before — Phase 5's handoff describes the
behavior ("client-side token-bucket throttling against
x-ratelimit-remaining-tokens", "TPM as the binding ceiling") but the
actual module was never built as a separate file. Creating it here so
both Phase 5's live consumer and Phase 6's report generator import the
SAME instance-shaped class against the SAME org-level Groq limits,
rather than each guessing independently.

Two layers of defense, matching the documented principle
("never trust one signal alone"):
  1. Local pre-emptive tracking (request timestamps + token totals in
     rolling windows) — used BEFORE every call to decide whether to wait.
  2. Optional recalibration from Groq's actual response headers, which
     are authoritative — used AFTER a call if the caller has access to
     raw headers (requires client.chat.completions.with_raw_response).
     Local tracking still works fine without this; it's a correction,
     not a requirement.

Defaults below match Groq's currently published free-tier limits for
openai/gpt-oss-120b (30 RPM / 1K RPD / 8K TPM / 200K TPD) as of this
build. These are configurable per-model since Groq publishes different
limits per model — do not assume they transfer if the model changes.
"""

import threading
import time
from collections import deque
from datetime import datetime, timezone


class RateLimitBudgetExceeded(Exception):
    """
    Raised when a daily (RPD/TPD) budget is exhausted. Daily limits are
    NOT worth sleeping through (could mean sleeping up to 24h) — callers
    must decide what to do (delay to next stream poll, alert an operator,
    etc.), not have this module block indefinitely.
    """
    pass


class TokenBucketThrottle:
    def __init__(
        self,
        model: str,
        rpm_limit: int = 30,
        rpd_limit: int = 1000,
        tpm_limit: int = 8000,
        tpd_limit: int = 200_000,
    ):
        self.model = model
        self.rpm_limit = rpm_limit
        self.rpd_limit = rpd_limit
        self.tpm_limit = tpm_limit
        self.tpd_limit = tpd_limit

        self._lock = threading.Lock()
        self._request_timestamps: deque = deque()   # rolling 60s window
        self._token_events: deque = deque()          # (ts, tokens), rolling 60s
        self._day_key = self._current_day_key()
        self._requests_today = 0
        self._tokens_today = 0

        # Set when update_from_headers() has authoritative data; None
        # means "trust local tracking only."
        self._header_remaining_tokens = None
        self._header_remaining_requests = None

    @staticmethod
    def _current_day_key() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _reset_day_if_needed(self):
        today = self._current_day_key()
        if today != self._day_key:
            self._day_key = today
            self._requests_today = 0
            self._tokens_today = 0
            self._header_remaining_tokens = None
            self._header_remaining_requests = None

    def _prune_minute_window(self):
        cutoff = time.monotonic() - 60
        while self._request_timestamps and self._request_timestamps[0] < cutoff:
            self._request_timestamps.popleft()
        while self._token_events and self._token_events[0][0] < cutoff:
            self._token_events.popleft()

    def _tokens_in_window(self) -> int:
        return sum(tokens for _, tokens in self._token_events)

    def wait_if_needed(self, estimated_tokens: int = 1500):
        """
        Call BEFORE making the Groq request. Blocks (sleeps) if the RPM
        or TPM window is currently full. Raises RateLimitBudgetExceeded
        if the DAILY budget (RPD/TPD) is exhausted — daily limits are not
        something to sleep through.
        """
        with self._lock:
            self._reset_day_if_needed()

            if self._requests_today >= self.rpd_limit:
                raise RateLimitBudgetExceeded(
                    f"{self.model}: daily request budget ({self.rpd_limit}) exhausted"
                )
            if self._tokens_today + estimated_tokens > self.tpd_limit:
                raise RateLimitBudgetExceeded(
                    f"{self.model}: daily token budget ({self.tpd_limit}) exhausted"
                )

            while True:
                self._prune_minute_window()

                rpm_ok = len(self._request_timestamps) < self.rpm_limit
                tpm_ok = self._tokens_in_window() + estimated_tokens <= self.tpm_limit

                if rpm_ok and tpm_ok:
                    break

                # Sleep until the oldest event in whichever window is
                # over budget falls out of the 60s rolling window.
                oldest_relevant = []
                if not rpm_ok and self._request_timestamps:
                    oldest_relevant.append(self._request_timestamps[0])
                if not tpm_ok and self._token_events:
                    oldest_relevant.append(self._token_events[0][0])

                sleep_for = max(0.5, (min(oldest_relevant) + 60) - time.monotonic()) \
                    if oldest_relevant else 1.0
                time.sleep(sleep_for)

            self._request_timestamps.append(time.monotonic())
            self._requests_today += 1

    def record_usage(self, usage):
        """
        Call AFTER a successful Groq response with response.usage.
        Records the ACTUAL token count (not the pre-call estimate) —
        this is what keeps the rolling window accurate over time instead
        of drifting from repeated estimate error.
        """
        total_tokens = getattr(usage, "total_tokens", None) or 0
        with self._lock:
            self._reset_day_if_needed()
            now = time.monotonic()
            self._token_events.append((now, total_tokens))
            self._tokens_today += total_tokens

    def update_from_headers(self, headers: dict):
        """
        Optional recalibration against Groq's authoritative rate-limit
        headers (x-ratelimit-remaining-tokens, x-ratelimit-remaining-requests).
        Only usable if the caller made the request via
        client.chat.completions.with_raw_response.create(...) and passes
        response.headers here. Safe to skip entirely — local tracking
        above is sufficient on its own.
        """
        with self._lock:
            remaining_tokens = headers.get("x-ratelimit-remaining-tokens")
            remaining_requests = headers.get("x-ratelimit-remaining-requests")
            if remaining_tokens is not None:
                self._header_remaining_tokens = int(remaining_tokens)
            if remaining_requests is not None:
                self._header_remaining_requests = int(remaining_requests)