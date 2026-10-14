"""One read-only acceptance-owner checkpoint sample; never logs credentials.

Uses the existing owner access token only. Does not log in, start/resume/cancel
research, call providers, or write runtime/checkpoint/cache files.
"""
import hashlib
import json
import re
import sys
from collections import Counter

import httpx

from live_acceptance_api import ACCESS, BASE, now, read_json
from live_research_acceptance import compact_batch, compact_batch_history, compact_tasks, safe_counter, safe_label


SID = "a8273040-32e1-4a1b-84b5-1a564c914fbf"
TARGET = "claim_5b130654dc4ca204"


def main():
    access = read_json(ACCESS)
    if not isinstance(access, dict) or access.get("api_base") != BASE:
        raise ValueError("Acceptance manifest unavailable or outside local API scope")
    owner = access["accounts"]["owner"]
    with httpx.Client(base_url=BASE, timeout=20, trust_env=False, follow_redirects=False,
                      headers={"Authorization": "Bearer " + owner["access_token"]}) as client:
        response = client.get(f"/research/checkpoint/{SID}/full")
    if response.status_code != 200:
        print(json.dumps({"observed_at": now(), "http_status": response.status_code}))
        return 1
    full = response.json().get("checkpoint") or {}
    if full.get("session_id") != SID or str(full.get("user_id")) != str(owner["user_id"]):
        raise ValueError("Checkpoint ownership does not match this acceptance session")
    state = full.get("state_json") or {}
    if sys.argv[1:] == ["--manual"]:
        def redact(value):
            text = str(value or "")
            for account in access["accounts"].values():
                for key in ("password", "access_token"):
                    if account.get(key):
                        text = text.replace(account[key], "[REDACTED]")
            text = re.sub(r"https?://\S+", "[URL]", text)
            return text[:1500]

        def target_claim(claims):
            target = next((c for c in claims or [] if c.get("claim_id") == TARGET), None)
            if target is None:
                return None
            text = target.get("claim_text") or target.get("text") or ""
            return {"claim_id": TARGET, "text_chars": len(text),
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "text_preview": redact(text), "verification_status": safe_label(target.get("verification_status")),
                "reason": redact(target.get("reason"))}

        history = state.get("review_history") or []
        archives = [{"resumed_at": row.get("resumed_at"),
                     "additional_iterations": row.get("additional_iterations"),
                     "used_existing_budget": row.get("used_existing_budget"),
                     "target": target_claim((row.get("state") or {}).get("claims"))} for row in history[-4:]]
        current = target_claim(state.get("claims"))
        previous = archives[-1]["target"] if archives else None
        manual = state.get("manual_review_request") or {}
        print(json.dumps({"observed_at": now(), "session_id": SID,
            "status": safe_label(full.get("status")), "phase": safe_label(state.get("phase")),
            "outcome": safe_label(state.get("outcome")), "review_verdict": safe_label(state.get("review_verdict")),
            "stop_reason": safe_label(state.get("stop_reason")),
            "iteration": safe_counter(state.get("iteration")), "max_iterations": safe_counter(state.get("max_iterations")),
            "manual": {key: manual.get(key) for key in ("applied", "requested_at", "claim_ids", "revised_claim_ids",
                "changed_claim_ids", "unchanged_requested_claim_ids", "hypothesis_review_status")},
            "target": current, "archives": archives,
            "changed_from_latest_archive": (current["text_sha256"] != previous["text_sha256"])
                if current and previous else None}, ensure_ascii=False, allow_nan=False))
        return 0
    retrieval = state.get("science_retrieval") or {}
    ledger = state.get("evidence_ledger") or {}
    events = []
    for message in state.get("messages") or []:
        if message.get("type") not in ("literature_progress", "analysis_search_decision", "analysis_complete", "review_search_decision"):
            continue
        content = message.get("content")
        if not isinstance(content, dict):
            continue
        event = {"type": safe_label(message.get("type")), "timestamp": message.get("timestamp")}
        for key in ("provider", "batch_id", "stop_reason", "budget_scope", "decision", "branch_status"):
            if key in content:
                event[key] = safe_label(content[key])
        for key in ("papers_count", "abstracts_count", "requests_used", "documents_used", "depth", "batch_queries_started", "gained_sources", "round"):
            if key in content:
                event[key] = safe_counter(content[key])
        for key in ("cached", "complete", "minimum_met", "approved"):
            if isinstance(content.get(key), bool):
                event[key] = content[key]
        events.append(event)
    output = {"observed_at": now(), "session_id": SID, "status": safe_label(full.get("status")),
        "phase": safe_label(state.get("phase")), "next_step": safe_label(state.get("_next_step")),
        "analysis_decision": safe_label(state.get("analysis_decision")),
        "outcome": safe_label(state.get("outcome")), "review_verdict": safe_label(state.get("review_verdict")),
        "stop_reason": safe_label(state.get("stop_reason")),
        "budget": {key: safe_counter(state.get(key)) for key in ("iteration", "max_iterations", "analysis_search_round", "review_search_round")},
        "retrieval_usage": {key: safe_counter(retrieval.get(key)) for key in ("requests_used", "documents_used", "elapsed_seconds", "batches_started", "papers_count")},
        "retrieval_stop_reason": safe_label(retrieval.get("stop_reason")), "budget_scope": safe_label(retrieval.get("budget_scope")),
        "active_batch": compact_batch(retrieval.get("active_batch"), retrieval),
        "batch_history": compact_batch_history(retrieval.get("batch_history")),
        "queue": compact_tasks(retrieval.get("queue")), "history": compact_tasks(retrieval.get("history")),
        "analysis_search_history": compact_tasks(state.get("analysis_search_history")),
        "review_search_history": compact_tasks(state.get("review_search_history")),
        "evidence_by_provider": dict(Counter(safe_label(e.get("provider")) or "other" for e in ledger.values())),
        "evidence_by_level": dict(Counter(safe_label(e.get("evidence_level")) or "other" for e in ledger.values())),
        "claims_count": len(state.get("claims") or []), "literature_errors_count": len(state.get("literature_errors") or []),
        "events": events[-35:], "events_omitted": max(0, len(events) - 35)}
    print(json.dumps(output, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"error_type": type(error).__name__}))
        raise SystemExit(1)
