"""Read-only quote-contract audit for the current synthetic acceptance research.

Run --collect only after the writer checkpoint is available. Reads the owner's
checkpoint through existing authenticated helpers, never starts/resumes research
or calls a model. Saves IDs/counts/booleans only; no full text or credentials.
"""
import argparse
from collections import Counter
import importlib.util
import json

from live_acceptance import ROOT, RUNTIME
from live_acceptance_api import now, read_json, write_private_json
from live_research_acceptance import ResearchAcceptance, digest

SESSION_ID = "c65524f1-41f5-41d2-8461-0834c922fae7"
RESULT = RUNTIME / "quote-acceptance.json"
TARGET_CLAIM = "claim_e67b6c6cdc1b4ea9"


def load_pure_evidence():
    path = ROOT / "backend/app/service/deep_research_v2/evidence.py"
    spec = importlib.util.spec_from_file_location("quote_audit_evidence", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def summarize(full, evidence_module):
    state = full.get("state_json") or {}
    ledger, claims = state.get("evidence_ledger") or {}, state.get("claims") or []
    manual = state.get("manual_review_request") or {}
    target = next((claim for claim in claims if claim.get("claim_id") == TARGET_CLAIM), None)
    target_history = []
    for row in state.get("review_history") or []:
        archive = row.get("state") if isinstance(row, dict) else None
        if not isinstance(archive, dict):
            continue
        previous = next((claim for claim in archive.get("claims", [])
                         if claim.get("claim_id") == TARGET_CLAIM), None)
        if previous is not None:
            target_history.append({"resumed_at": row.get("resumed_at"),
                "text_changed_from_archive": target is not None and previous.get("claim_text") != target.get("claim_text"),
                "links_changed_from_archive": target is not None and previous.get("evidence_links") != target.get("evidence_links"),
                "previous_text_chars": len(previous.get("claim_text") or ""),
                "previous_text_sha256": digest(previous.get("claim_text")),
                "previous_semantic_status": previous.get("verification_status")})
    rows, per_claim, fresh_errors = [], [], []
    for claim in claims:
        quote_rows = []
        for index, link in enumerate(claim.get("evidence_links") or []):
            if not link.get("quote_id"):
                continue
            eid = link.get("evidence_id")
            source = ledger.get(eid) or {}
            asset = next((asset for asset in source.get("assets", [])
                          if asset.get("asset_id") == link.get("asset_id")), None) if link.get("asset_id") else None
            content = str((asset if asset is not None else source).get("content") or "")
            excerpt, span = link.get("quote"), link.get("text_span")
            original_quote = isinstance(excerpt, str) and bool(excerpt) and excerpt in content
            span_matches = (isinstance(span, dict) and all(type(span.get(key)) is int for key in ("start", "end"))
                            and 0 <= span["start"] < span["end"] <= len(content)
                            and isinstance(excerpt, str) and content[span["start"]:span["end"]] == excerpt)
            candidate = next((candidate for candidate in evidence_module.evidence_quote_candidates(source)
                              if candidate["quote_id"] == link["quote_id"]), None)
            candidate_matches = (candidate is not None and candidate.get("asset_id") == link.get("asset_id")
                                 and candidate["quote"] == excerpt and candidate["text_span"] == span)
            identity_matches = (eid in (claim.get("evidence_ids") or []) and bool(source)
                and all(source.get(key) is not None and str(source[key]) == str(link.get(key))
                        for key in ("knowledge_base_id", "document_id", "document_version", "chunk_id"))
                and (not link.get("asset_id") or asset is not None
                     and asset.get("document_id") == source.get("document_id")
                     and asset.get("document_version") == source.get("document_version")))
            _, errors = evidence_module.normalize_evidence_links(state, claim.get("evidence_ids") or [], [link])
            row = {"claim_id": claim.get("claim_id"), "link_index": index, "evidence_id": eid,
                   "quote_id": link["quote_id"], "asset_id": link.get("asset_id"),
                   "quote_chars": len(excerpt) if isinstance(excerpt, str) else 0,
                   "raw_substring_matches": original_quote, "raw_span_matches": span_matches,
                   "source_identity_matches": identity_matches, "candidate_matches": candidate_matches,
                   "full_locator_validation_passed": not errors,
                   "validation_error_categories": dict(Counter(error.get("reason") for error in errors)),
                   "precision": link.get("precision"), "visual_verification": link.get("visual_verification"),
                   "semantic_status": claim.get("verification_status")}
            rows.append(row)
            quote_rows.append(row)
        _, current_errors = evidence_module.normalize_evidence_links(
            state, claim.get("evidence_ids") or [], claim.get("evidence_links"))
        fresh_errors.extend(current_errors)
        per_claim.append({"claim_id": claim.get("claim_id"), "quote_id_links": len(quote_rows),
                          "citation_precision": claim.get("citation_precision"),
                          "semantic_status": claim.get("verification_status"),
                          "saved_location_errors": dict(Counter(error.get("reason") for error in claim.get("evidence_link_errors", []))),
                          "current_location_errors": dict(Counter(error.get("reason") for error in current_errors))})
    checks = ("raw_substring_matches", "raw_span_matches", "source_identity_matches", "candidate_matches",
              "full_locator_validation_passed")
    totals = {key: {"matched": sum(bool(row[key]) for row in rows), "total": len(rows),
                    "rate": sum(bool(row[key]) for row in rows) / len(rows) if rows else None} for key in checks}
    return {"observed_at": now(), "session_id": full.get("session_id"), "status": full.get("status"),
            "phase": state.get("phase"), "iteration": state.get("iteration"),
            "review_extension_rounds": state.get("review_extension_rounds"),
            "review_verdict": state.get("review_verdict"), "outcome": state.get("research_outcome") or state.get("outcome"),
            "claims_count": len(claims), "semantic_status_counts": dict(Counter(claim.get("verification_status") for claim in claims)),
            "quote_id_adoption": "observed" if rows else "not_observed",
            "quote_id_links": len(rows), "quote_id_claims": sum(bool(row["quote_id_links"]) for row in per_claim),
            "asset_quote_id_links": sum(bool(row["asset_id"]) for row in rows), "consistency": totals,
            "citation_errors_count": len(state.get("citation_errors") or []),
            "citation_error_categories": dict(Counter(error.get("reason") for error in state.get("citation_errors", []))),
            "saved_location_error_categories": dict(Counter(error.get("reason") for claim in claims for error in claim.get("evidence_link_errors", []))),
            "current_location_error_categories": dict(Counter(error.get("reason") for error in fresh_errors)),
            "target_claim": next((row for row in per_claim if row["claim_id"] == TARGET_CLAIM), None),
            "target_claim_comparison": {"current_text_chars": len((target or {}).get("claim_text") or ""),
                "current_text_sha256": digest((target or {}).get("claim_text")),
                "history": target_history},
            "manual_review": {"notes_chars": len(manual.get("notes") or ""),
                "claim_ids": manual.get("claim_ids") or [], "applied": manual.get("applied"),
                "hypothesis_review_status": manual.get("hypothesis_review_status"),
                "revised_claim_ids": manual.get("revised_claim_ids") or [],
                "changed_claim_ids": manual.get("changed_claim_ids") or [],
                "unchanged_requested_claim_ids": manual.get("unchanged_requested_claim_ids") or []},
            "quality_review_status": state.get("quality_review_status"),
            "task_coverage_status": (state.get("task_coverage_review") or {}).get("status"),
            "stop_reason": state.get("stop_reason"),
            "claims": per_claim, "links": rows,
            "checkpoint_digest": digest({key: full.get(key) for key in ("state_json", "ui_state_json", "final_report", "status")}),
            "scope": "Observed provenance integrity only; not an assertion that every claim is semantically supported."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect", action="store_true")
    if not parser.parse_args().collect:
        parser.error("No API request made; explicitly pass --collect after writer checkpoint availability")
    acceptance = ResearchAcceptance("quote_contract_readonly", SESSION_ID)
    result = {"observed_at": now(), "session_id": SESSION_ID, "success": False}
    try:
        client = acceptance.authenticated("owner")
        full = acceptance.checkpoint(client)
        summary = summarize(full, load_pure_evidence())
        result.update(summary, success=True)
    except Exception as error:
        result["error_type"] = type(error).__name__
    finally:
        for client in acceptance.clients:
            client.close()
    previous = read_json(RESULT, {"schema_version": 1, "samples": []})
    previous.setdefault("samples", []).append(result)
    previous["latest"] = result
    write_private_json(RESULT, previous)
    print(json.dumps({key: value for key, value in result.items() if key not in ("claims", "links")}, ensure_ascii=False))
    raise SystemExit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
