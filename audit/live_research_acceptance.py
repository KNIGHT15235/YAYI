"""Collect this acceptance owner's research status without starting research.

collect/isolation are read-only API probes. overwrite is an explicit, terminal-
run-only rejection probe: expected HTTP 409; it never consumes a research stream.
No account/session creation, resume, cancel, deletion, or provider call is used.
"""
import argparse
import hashlib
import json
import math
import re
from collections import Counter
from uuid import UUID

from live_acceptance_api import Acceptance, RUNTIME, now, read_json, write_private_json


RESULT = RUNTIME / "research-acceptance.json"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def compact_locator(value):
    if not isinstance(value, dict):
        return {}
    # Avoid retaining full table content or provider-signed URLs.
    allowed = ("type", "page", "page_number", "table_id", "table_index", "table_number",
               "row", "row_index", "row_start", "row_end", "row_indices", "equation_id", "formula_id", "bbox")
    return {key: value[key] for key in allowed if key in value}


def compact_tasks(rows):
    rows = rows or []
    result = []
    for row in rows[-12:]:
        if not isinstance(row, dict):
            result.append({"entry_chars": len(str(row))})
            continue
        item = {key: row.get(key) for key in ("id", "task_id", "claim_id", "claim_ids", "section_id",
            "action", "status", "depth", "recursive", "charged", "parent_id", "applied", "requested_at") if key in row}
        item.update({key + "_chars": len(str(row.get(key) or "")) for key in ("query", "reason", "notes")})
        if "gained_evidence_ids" in row:
            item["gained_evidence_count"] = len(row.get("gained_evidence_ids") or [])
        result.append(item)
    return {"count": len(rows), "last_entries": result, "omitted_entries": max(0, len(rows) - 12)}


def safe_counter(value):
    # A malformed provider/string payload must not appear as a budget counter.
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def safe_label(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value) else None


def compact_batch(batch, retrieval=None):
    if not isinstance(batch, dict):
        return None
    summary = {key: safe_label(batch.get(key)) for key in ("id", "origin", "status", "stop_reason", "budget_scope")}
    limits = batch.get("limits") if isinstance(batch.get("limits"), dict) else {}
    summary["limits"] = {key: safe_counter(limits[key]) for key in (
        "max_batch_queries", "max_batch_requests", "max_batch_documents", "max_batch_seconds", "max_batch_papers") if key in limits}
    for key in ("requests_start", "documents_start", "requests_used", "documents_used", "elapsed_seconds",
                "queries_started", "recursive_queries_used", "papers_start", "papers_added", "papers_count"):
        if key in batch:
            summary[key] = safe_counter(batch[key])
    # Active batches persist starts, while finished batches also persist deltas.
    # Infer only known request/document deltas, never papers_added from net corpus
    # size: de-duplication can shrink the corpus without refunding used allowance.
    if isinstance(retrieval, dict) and batch.get("status") == "running":
        for used, start in (("requests_used", "requests_start"), ("documents_used", "documents_start")):
            total, initial = safe_counter(retrieval.get(used)), safe_counter(batch.get(start))
            if used not in summary and total is not None and initial is not None and total >= initial:
                summary[used] = total - initial
    return summary


def compact_batch_history(rows):
    rows = rows if isinstance(rows, list) else []
    return {"count": len(rows), "last_entries": [compact_batch(row) for row in rows[-12:]],
            "omitted_entries": max(0, len(rows) - 12)}


def compact_review_history(rows):
    rows = rows if isinstance(rows, list) else []
    summaries = []
    for row in rows[-4:]:
        if not isinstance(row, dict):
            continue
        archive = row.get("state") if isinstance(row.get("state"), dict) else {}
        report = archive.get("final_report")
        summaries.append({"resumed_at": row.get("resumed_at"), "additional_iterations": row.get("additional_iterations"),
            "used_existing_budget": row.get("used_existing_budget"),
            "notes_chars": len(row.get("review_notes") or ""), "claim_ids": row.get("review_claim_ids") or [],
            "archive_report_chars": len(report) if isinstance(report, str) else None,
            "archive_report_sha256": hashlib.sha256(report.encode("utf-8")).hexdigest() if isinstance(report, str) else None,
            "archive_claims_count": len(archive["claims"]) if isinstance(archive.get("claims"), list) else None})
    return summaries


def summarize_checkpoint(full, resources, redact):
    state = full.get("state_json") or {}
    ui = full.get("ui_state_json") or {}
    ledger = state.get("evidence_ledger") or {}
    claims = state.get("claims") or []
    report = state.get("final_report") or full.get("final_report") or ""
    table_assets, evidence_rows = set(), []
    for eid, evidence in ledger.items():
        assets = evidence.get("assets") or []
        table_assets.update(a.get("asset_id") for a in assets if a.get("type") == "table" and a.get("asset_id"))
        evidence_rows.append({"evidence_id": eid, "document_id": evidence.get("document_id"),
            "document_version": evidence.get("document_version"), "knowledge_base_id": evidence.get("knowledge_base_id"),
            "evidence_level": evidence.get("evidence_level"), "content_chars": len(evidence.get("content") or ""),
            "locator_count": len(evidence.get("locators") or []),
            "assets": [{key: asset.get(key) for key in ("asset_id", "type", "document_id", "document_version")}
                       for asset in assets]})
    claim_rows, unknown_ids, table_claim_ids, explicit_table_links = [], set(), set(), 0
    for claim in claims:
        ids = claim.get("evidence_ids") or []
        unknown_ids.update(eid for eid in ids if eid not in ledger)
        links = []
        for link in claim.get("evidence_links") or []:
            loc = compact_locator(link.get("locator"))
            table_link = (link.get("asset_id") in table_assets or any(
                key in loc for key in ("table_id", "table_index", "table_number", "row", "row_index", "row_indices")))
            if table_link:
                explicit_table_links += 1
                table_claim_ids.add(claim.get("claim_id"))
            links.append({"evidence_id": link.get("evidence_id"), "asset_id": link.get("asset_id"),
                          "locator": loc, "quote_chars": len(link.get("quote") or ""), "table_link": table_link})
        claim_rows.append({"claim_id": claim.get("claim_id"), "section_id": claim.get("section_id"),
            "text_preview": redact((claim.get("claim_text") or claim.get("text") or "")[:300]),
            "verification_status": claim.get("verification_status"), "evidence_ids": ids, "evidence_links": links})
    local = [row for row in evidence_rows if row["document_id"]]
    expected_version = resources.get("fixture_sha256")
    retrieval = state.get("science_retrieval") or {}
    manual = state.get("manual_review_request") or {}
    return {"observed_at": now(), "session_id": full.get("session_id"), "status": full.get("status"),
        "phase": state.get("phase", full.get("phase")), "next_step": state.get("_next_step"),
        "outcome": state.get("outcome"), "research_outcome": state.get("research_outcome"),
        "review_verdict": state.get("review_verdict"), "stop_reason": state.get("stop_reason"),
        "quality_review_status": state.get("quality_review_status"), "quality_score": state.get("quality_score"),
        "quality_review_note": redact(state.get("quality_review_note") or ""),
        "search_local": state.get("search_local"), "search_web": state.get("search_web"),
        "analysis_decision": state.get("analysis_decision"),
        "agent_models": (state.get("research_profile") or {}).get("agent_models", {}),
        "budget": {key: state.get(key) for key in ("iteration", "max_iterations", "analysis_search_round",
                    "review_search_round", "review_retry_count", "review_extension_rounds")},
        "retrieval_usage": {**{key: retrieval.get(key) for key in ("requests_used", "documents_used",
            "recursive_queries_used", "elapsed_seconds", "batches_started", "stop_reason", "papers_count", "paper_limit")},
            "budget_scope": safe_label(retrieval.get("budget_scope")),
            "active_batch": compact_batch(retrieval.get("active_batch"), retrieval),
            "batch_history": compact_batch_history(retrieval.get("batch_history")),
            "queue": compact_tasks(retrieval.get("queue")), "history": compact_tasks(retrieval.get("history")),
            "visited_count": len(retrieval.get("visited") or [])},
        "analysis_search_history": compact_tasks(state.get("analysis_search_history")),
        "review_search_history": compact_tasks(state.get("review_search_history")),
        "review_repair_actions": compact_tasks(state.get("review_repair_actions")),
        "repair_analysis_count": len(state.get("repair_analysis_history") or []),
        "review_requests": {
            "manual": {"notes_chars": len(manual.get("notes") or ""), "claim_ids": manual.get("claim_ids") or [],
                       "applied": manual.get("applied"), "requested_at": manual.get("requested_at"),
                       "hypothesis_review_status": manual.get("hypothesis_review_status"),
                       "revised_claim_ids": manual.get("revised_claim_ids") or [],
                       "changed_claim_ids": manual.get("changed_claim_ids") or [],
                       "unchanged_requested_claim_ids": manual.get("unchanged_requested_claim_ids") or []},
            "revision_requests": compact_tasks(state.get("review_revision_requests")),
            "history_count": len(state.get("review_history") or []),
            "history": compact_review_history(state.get("review_history"))},
        "steps": [{key: step.get(key) for key in ("type", "status", "start_time", "end_time")}
                  for step in ui.get("research_steps") or []],
        "report_chars": len(report), "report_sha256": hashlib.sha256(report.encode("utf-8")).hexdigest(),
        "papers_count": len(state.get("papers") or []), "claims_count": len(claims),
        "charts_count": len(state.get("charts") or []), "references_count": len(state.get("references") or []),
        "claim_status_counts": dict(Counter(str(c.get("verification_status")) for c in claims)),
        "evidence_count": len(evidence_rows), "local_evidence_count": len(local),
        "own_document_evidence_count": sum(row["document_id"] == resources.get("document_id") for row in local),
        "local_identity_binding_valid": bool(local) and all(
            row["document_id"] == resources.get("document_id")
            and row["document_version"] == expected_version
            and row["knowledge_base_id"] == resources.get("knowledge_base_id") for row in local),
        "unknown_claim_evidence_ids": sorted(unknown_ids),
        "table_asset_count": len(table_assets), "explicit_table_link_count": explicit_table_links,
        "claims_with_explicit_table_links": len(table_claim_ids),
        "evidence": evidence_rows, "claims": claim_rows,
        "checkpoint_digest": digest({key: full.get(key) for key in ("state_json", "ui_state_json", "final_report", "status")}),
        "error": redact(full.get("error_message") or "")}


class ResearchAcceptance(Acceptance):
    def __init__(self, command, session_id):
        super().__init__(command)
        self.session_id = str(UUID(session_id))
        self.research_results = read_json(RESULT, {"schema_version": 1, "sessions": {}, "runs": []})

    def checkpoint(self, client):
        response = self.request(client, "read owned full checkpoint", "GET", f"/research/checkpoint/{self.session_id}/full")
        payload = response.json()
        self.require("requested research checkpoint exists", payload.get("success") is True and bool(payload.get("checkpoint")))
        full = payload["checkpoint"]
        self.require("research belongs to this acceptance owner",
                     full.get("session_id") == self.session_id
                     and full.get("user_id") == self.access["accounts"]["owner"]["user_id"])
        resources = self.resources()
        state = full.get("state_json") or {}
        self.require("research uses only this run's knowledge base",
                     state.get("knowledge_base_id") == resources["knowledge_base_id"]
                     and state.get("kb_name") == resources["knowledge_base_name"]
                     and state.get("search_local") is True)
        return full

    def collect(self):
        owner = self.authenticated("owner")
        full = self.checkpoint(owner)
        summary = summarize_checkpoint(full, self.resources(), self.redact)
        entry = self.research_results["sessions"].setdefault(self.session_id, {"samples": []})
        entry["samples"].append(summary)
        entry["latest"] = summary
        compact = {key: value for key, value in summary.items() if key not in ("evidence", "claims")}
        print(json.dumps(compact, ensure_ascii=False))

    def isolation(self):
        owner = self.authenticated("owner")
        full = self.checkpoint(owner)
        paths = [f"/research/checkpoint/{self.session_id}", f"/research/checkpoint/{self.session_id}/full",
                 f"/sessions/{self.session_id}"]
        matrix = []
        for role, client, status in (("other", self.authenticated("other"), 404), ("anonymous", self.client(), 401)):
            for path in paths:
                response = self.request(client, role + " cannot read owned research", "GET", path,
                                        expected=status, required=False)
                matrix.append({"role": role, "path": path, "status": response.status_code if response is not None else None,
                               "expected_status": status})
        self.research_results["sessions"].setdefault(self.session_id, {"samples": []})["isolation"] = matrix

    def overwrite(self):
        owner = self.authenticated("owner")
        before = self.checkpoint(owner)
        self.require("overwrite rejection probe requires terminal checkpoint", before.get("status") in ("completed", "failed"))
        state = before["state_json"]
        body = {"query": before["query"], "session_id": self.session_id,
                "version": "v2", "profile_id": state.get("profile_id", "science"),
                "kb_name": state["kb_name"], "search_local": True, "search_web": False, "max_iterations": 1}
        # Do not read a 200 stream: it would indicate a server regression.
        with owner.stream("POST", "/research/stream", json=body) as response:
            status = response.status_code
            if status != 409:
                self.check("existing checkpoint rejected before execution", False, status=status, expected_status=409)
                raise RuntimeError("Unexpected overwrite response; connection closed without consuming a research stream")
            response.read()
            payload = response.json()
            detail = payload.get("detail") or {}
            self.require("specific research_run_exists protection reached",
                         isinstance(detail, dict) and detail.get("code") == "research_run_exists"
                         and detail.get("run_id") == self.session_id, status=status)
        after = self.checkpoint(owner)
        stable_keys = ("state_json", "ui_state_json", "final_report", "status")
        before_hash = digest({key: before.get(key) for key in stable_keys})
        after_hash = digest({key: after.get(key) for key in stable_keys})
        self.check("rejected overwrite leaves complete checkpoint unchanged", before_hash == after_hash)
        self.research_results["sessions"].setdefault(self.session_id, {"samples": []})["overwrite"] = {
            "status": status, "before_digest": before_hash, "after_digest": after_hash,
            "unchanged": before_hash == after_hash}

    def finish(self, error=None):
        if error is not None:
            self.check("command completed", False, error_type=type(error).__name__, error=self.redact(error))
        for client in self.clients:
            client.close()
        failed = [row for row in self.checks if not row["passed"]]
        summary = {"command": self.command, "session_id": self.session_id, "started_at": self.started_at,
            "finished_at": now(), "passed": len(self.checks) - len(failed), "total": len(self.checks), "failed": len(failed),
            "checks": self.checks, "data_deleted": False}
        self.research_results["runs"].append(summary)
        self.research_results["updated_at"] = now()
        write_private_json(RESULT, self.research_results)
        print(json.dumps({key: value for key, value in summary.items() if key != "checks"}, ensure_ascii=False))
        if failed:
            print(json.dumps({"failures": failed}, ensure_ascii=False))
        return 1 if failed else 0


def selfcheck():
    """Pure offline fixture checks; no settings/account reads or HTTP clients."""
    secret = "DO_NOT_OUTPUT_SYNTHETIC_SECRET"
    provider_url = "https://provider.invalid/private?token=" + secret
    batch = {"id": "batch_2", "origin": "supplementary", "status": "running", "stop_reason": "max_batch_papers",
        "budget_scope": "batch", "limits": {"max_batch_requests": 8, "max_batch_papers": 60, "provider_url": provider_url},
        "requests_start": 8, "documents_start": 100, "elapsed_seconds": 13.5, "queries_started": 2,
        "papers_start": 12, "papers_added": 5, "query": secret, "provider_url": provider_url}
    active = compact_batch(batch, {"requests_used": 11, "documents_used": 150})
    assert active["requests_used"] == 3 and active["documents_used"] == 50
    assert active["papers_added"] == 5 and active["limits"]["max_batch_papers"] == 60
    assert secret not in json.dumps(active) and "provider_url" not in json.dumps(active)
    finished = compact_batch({**batch, "status": "completed", "requests_used": 3}, {"requests_used": 99})
    assert finished["requests_used"] == 3  # Later total usage must not inflate an archived batch.
    history = compact_batch_history([batch] * 14)
    assert history["count"] == 14 and len(history["last_entries"]) == 12 and history["omitted_entries"] == 2
    malformed = compact_batch({"id": provider_url, "limits": {"max_batch_papers": secret}, "papers_added": float("nan")})
    assert malformed["id"] is None and malformed["limits"]["max_batch_papers"] is None and malformed["papers_added"] is None
    assert compact_batch(None) is None
    state = {"science_retrieval": {"budget_scope": "batch", "active_batch": batch, "batch_history": [finished]},
        "manual_review_request": {"notes": secret, "applied": False, "changed_claim_ids": ["claim_changed"],
                                  "unchanged_requested_claim_ids": ["claim_unchanged"]},
        "review_history": [{"review_notes": secret, "state": {"final_report": secret,
                            "claims": [{"claim_text": secret}], "provider_url": provider_url}}]}
    summary = summarize_checkpoint({"state_json": state}, {}, lambda text: text.replace(secret, "[REDACTED]"))
    request = summary["review_requests"]
    assert request["history_count"] == 1 and request["history"][0]["archive_claims_count"] == 1
    assert request["history"][0]["archive_report_sha256"] == hashlib.sha256(secret.encode()).hexdigest()
    assert request["manual"]["changed_claim_ids"] == ["claim_changed"]
    assert request["manual"]["unchanged_requested_claim_ids"] == ["claim_unchanged"]
    assert secret not in json.dumps(summary) and provider_url not in json.dumps(summary)
    assert summary["retrieval_usage"]["active_batch"]["papers_added"] == 5
    print(json.dumps({"command": "selfcheck", "passed": True, "external_requests": 0, "credentials_read": False}))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("collect", "isolation", "overwrite", "selfcheck"))
    parser.add_argument("session_id", type=str, nargs="?")
    args = parser.parse_args()
    if args.command == "selfcheck":
        return selfcheck()
    if not args.session_id:
        parser.error("session_id is required for API probes")
    try:
        UUID(args.session_id)
    except ValueError:
        parser.error("session_id must be a UUID")
    acceptance = ResearchAcceptance(args.command, args.session_id)
    try:
        getattr(acceptance, args.command)()
    except Exception as error:
        return acceptance.finish(error)
    return acceptance.finish()


if __name__ == "__main__":
    raise SystemExit(main())
