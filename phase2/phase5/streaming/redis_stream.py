"""
Phase 5 — Redis Streams wiring.

Replaces synchronous/polling triggering: Phase 4's impact-matching engine pushes
an entry onto the stream whenever it writes an IMPACTS relationship with
alert_triggered = true. A separate consumer process drains the stream at a pace
the Groq TPM budget can sustain (paced by the TokenBucket in groq_client.py,
not by stream consumption speed itself — the consumer can read fast, the
Groq call is what's throttled).

STREAM_NAME must be added to Phase 4's write path — this file only defines
producer/consumer; wiring the produce() call into Phase 4's existing
alert-write code is a small edit to that module, not shown here since it's
outside phase5/.
"""
from __future__ import annotations
import json
import logging
import redis

STREAM_NAME = "supply_chain:alerts"
CONSUMER_GROUP = "phase5_agent_workers"
CONSUMER_NAME = "worker-1"

# Phase 7 — second stream, Phase 5 -> Phase 7, "an AgentAssessment now exists".
# Separate from STREAM_NAME above (Phase 4 -> Phase 5, "an event needs scoring") —
# distinct producers, distinct consumers, distinct concerns.
ASSESSMENT_STREAM_NAME = "supply_chain:assessments_created"
ASSESSMENT_CONSUMER_GROUP = "phase7_alert_workers"

logger = logging.getLogger("phase5.redis_stream")


def get_redis_client(host: str = "redis", port: int = 6379) -> redis.Redis:
    return redis.Redis(host=host, port=port, decode_responses=True)


def ensure_consumer_group(r: redis.Redis):
    try:
        r.xgroup_create(STREAM_NAME, CONSUMER_GROUP, id="0", mkstream=True)
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise  # group already exists, fine


def produce_alert(r: redis.Redis, customer_id: str, event_id: str, supplier_id: str, title: str, event_text: str):
    """Call this from Phase 4's write_impact(), right after a successful
    IMPACTS write with alert_triggered=true. supplier_id is required —
    Phase 4's WRITE_IMPACTS merge key is (event_id, customer_id, supplier_id),
    and Phase 5 must carry that same granularity through, not guess it later."""
    r.xadd(STREAM_NAME, {
        "customer_id": customer_id,
        "event_id": event_id,
        "supplier_id": supplier_id,
        "title": title,
        "event_text": event_text,
    })

def produce_assessment_created(r: redis.Redis, assessment_id: str, customer_id: str,
                                initial_severity: str | None, status: str, event_id: str):
    """Call this from persist.py's persist_agent_assessment(), right after a
    successful AgentAssessment MERGE. initial_severity (Phase 4's pre-LLM
    severity, set regardless of whether the Groq call succeeded) is what
    Phase 7's alert consumer filters on — not `severity`, which is None for
    every needs_review row since it only gets set when `prediction is not None`."""
    r.xadd(ASSESSMENT_STREAM_NAME, {
        "assessment_id": assessment_id,
        "customer_id": customer_id,
        "initial_severity": initial_severity or "",
        "status": status,
        "event_id": event_id,
    })


def consume_loop(r: redis.Redis, handler, block_ms: int = 5000, batch_size: int = 5):
    """
    handler: callable(customer_id: str, event_id: str, supplier_id: str, title: str, event_text: str) -> None
    Runs indefinitely, acking each entry only after handler succeeds so a crash
    mid-processing leaves the entry pending for redelivery rather than lost.
    """
    ensure_consumer_group(r)
    while True:
        entries = r.xreadgroup(
            CONSUMER_GROUP, CONSUMER_NAME,
            {STREAM_NAME: ">"}, count=batch_size, block=block_ms,
        )
        if not entries:
            continue

        for _stream, messages in entries:
            for msg_id, fields in messages:
                try:
                    handler(fields["customer_id"], fields["event_id"], fields["supplier_id"],
                             fields["title"], fields["event_text"])
                    r.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
                except Exception:
                    logger.exception(f"Handler failed for message {msg_id}, leaving unacked for retry")