"""
Phase 6 — cluster_themes.py

Deterministic, code-side clustering. The LLM never invents groupings —
it only narrates the clusters this module produces.

Also deduplicates near-verbatim recommended actions within a cluster
before the payload reaches the prompt — same rationale as clustering
itself: dedup logic should be auditable in code, not left to the model
to notice on its own.

Clustering dimension for v1: supplier_id only. Product-overlap clustering
(same component hitting multiple products) is a distinct pattern and a
candidate v1.1 addition — deliberately not merged into this pass so the
grouping logic stays auditable ("why was this grouped" always has a
one-line answer: same supplier_id).
"""

from collections import defaultdict
from difflib import SequenceMatcher

# Actions with normalized-text similarity above this threshold are treated
# as duplicates. 0.85 catches near-verbatim rewordings (see TSMC "contact
# immediately" duplicate) without merging genuinely distinct actions.
SIMILARITY_THRESHOLD = 0.85


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _dedupe_actions(actions: list) -> list[dict]:
    print(">>> RUNNING PATCHED cluster_themes.py <<<")
    if isinstance(actions, str):
        raise TypeError(
           "_dedupe_actions received a raw JSON string, not a parsed list — "
           "caller must json.loads() recommended_actions_json first."
        )
    deduped: list[dict] = []
    for action in actions:
        # Normalize shape: some assessments store actions as plain strings,
        # others as dicts ({"action": ..., "rationale": ..., "urgency": ...}).
        # Coerce strings into the dict shape so downstream code (and the
        # prompt) always sees a consistent structure.
        if isinstance(action, str):
            action = {"action": action, "rationale": "", "urgency": ""}
        elif not isinstance(action, dict):
            continue  # skip anything unexpected rather than crash

        action_text = _normalize(action.get("action", ""))
        if not action_text:
            continue

        is_duplicate = False
        for kept in deduped:
            kept_text = _normalize(kept.get("action", ""))
            similarity = SequenceMatcher(None, action_text, kept_text).ratio()
            if similarity >= SIMILARITY_THRESHOLD:
                is_duplicate = True
                break
        if not is_duplicate:
            deduped.append(action)
    return deduped

def _collect_actions(assessments: list[dict], assessment_ids: list[str]) -> list:
    import json
    id_set = set(assessment_ids)
    actions: list = []
    for a in assessments:
        if a["assessment_id"] in id_set:
            raw = a.get("recommended_actions_json") or []
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    raw = []
            actions.extend(raw)
    return actions



def cluster_by_theme(assessments: list[dict]) -> list[dict]:
    by_supplier = defaultdict(list)
    for a in assessments:
        by_supplier[a["supplier_id"]].append(a["assessment_id"])

    clusters = []
    grouped_ids = set()

    for supplier_id, assessment_ids in by_supplier.items():
        if len(assessment_ids) >= 2:
            deduped_actions = _dedupe_actions(_collect_actions(assessments, assessment_ids))
            clusters.append({
                "supplier_id": supplier_id,
                "assessment_ids": assessment_ids,
                "shared_cause": "supplier_match",
                "recommended_actions": deduped_actions,
            })
            grouped_ids.update(assessment_ids)

    # Ungrouped assessments still get a single-item "theme" so every
    # incident belongs to exactly one theme section in the prompt contract —
    # none silently dropped from the THEMES output.
    for a in assessments:
        if a["assessment_id"] not in grouped_ids:
            deduped_actions = _dedupe_actions(
                _collect_actions(assessments, [a["assessment_id"]])
            )
            clusters.append({
                    "supplier_id": a["supplier_id"],
                    "assessment_ids": [a["assessment_id"]],
                    "shared_cause": "single_incident",
                    "recommended_actions": deduped_actions,
                })

    return clusters