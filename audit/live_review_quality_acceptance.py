"""Bounded, opt-in scientific review and manual-edit live acceptance.

micro only GETs the old checkpoint and reviews a deepcopy in memory. migration
only replays manual-state migration in memory, without any model or task write.
run/manual use ordinary authenticated session/SSE endpoints and retain their new session ID.
No historical checkpoint, provider credential, or raw model response is written.
Artifacts are safe summaries in the existing git-ignored acceptance runtime.
"""
import argparse
import asyncio
from collections import Counter
from copy import deepcopy
import hashlib
import json
import logging
import re
import time
from uuid import UUID

import httpx

from live_acceptance_api import Acceptance, RUNTIME, now, read_json, write_private_json
from live_research_acceptance import digest, safe_counter, safe_label


RESULT = RUNTIME / "review-quality-acceptance.json"
OLD_SESSION = "a8273040-32e1-4a1b-84b5-1a564c914fbf"
MICRO_CASES = (
    ("old_unverified", "claim_8804292d40c192a0"),
    ("domain_absence", "claim_caeee6ffcad02b1d"),
    ("bounded_synthetic", "claim_fa8844681a96c9e7"),
)
QUERY = (
    "仅根据知识库中标记 YAYI-LIVE-20261014 的合成工程测试文档，"
    "用清晰的小节解释 Table 1 的 Lexical-only、Vector-only 与 Hybrid RRF "
    "Recall@20 和 p50 延迟，并复算 Hybrid 相对 Vector 的召回百分点差与延迟差。"
    "只描述该合成表的配置、计算与适用范围，不生成真实领域综述，"
    "不推断领域不存在某项研究，不外推真实效果、显著性或生产扩展能力。"
    "缺失信息明确保留未知，不编造新事实。"
)
MANUAL_NOTES = (
    "请实际改写所选声明的正文，将其组织为一段明确的合成样本口径说明："
    "写清原文已有的100条合成查询、500条合成文档、相关性标注人为设定，"
    "并明确这些数字仅用于合成工程测试，不代表真实学科实验证据。"
    "上述事实若已零散出现，仍请合并重写为边界清楚的一段，不仅替换引用或调整格式；"
    "不能把本意见当作新证据，逐项以本地原文为准。"
    "其他声明的自动审核问题继续独立处理，不作为本次指定正文修改是否实施的条件。"
)
STABLE_CHECKPOINT_KEYS = ("state_json", "ui_state_json", "final_report", "status")


def body_hash(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def checkpoint_digest(full):
    return digest({key: full.get(key) for key in STABLE_CHECKPOINT_KEYS})


def short_label(value):
    return safe_label(value)


class ReviewQualityAcceptance(Acceptance):
    def __init__(self, command):
        super().__init__(command)
        self.results = read_json(RESULT, {"schema_version": 1, "runs": [], "sessions": {}})
        self.current = {"command": command, "started_at": self.started_at}

    def safe_text(self, value, limit=600):
        # Existing redactor removes known secrets; signed URLs are never retained.
        return re.sub(r"https?://\S+", "[URL]", self.redact(value))[:limit]

    def owned_checkpoint(self, client, session_id):
        session_id = str(UUID(session_id))
        response = self.request(client, "GET owned checkpoint", "GET", f"/research/checkpoint/{session_id}/full")
        payload = response.json()
        full = payload.get("checkpoint") or {}
        self.require("checkpoint identity belongs to acceptance owner",
                     payload.get("success") is True and full.get("session_id") == session_id
                     and str(full.get("user_id")) == str(self.access["accounts"]["owner"]["user_id"]))
        return full

    def read_only_owner(self):
        # collect never logs in or refreshes a token. An expired token fails closed.
        self.validate_access()
        token = self.access["accounts"]["owner"].get("access_token")
        self.require("existing owner token is available", bool(token))
        client = self.client()
        client.headers["Authorization"] = "Bearer " + token
        return client

    def claim_summary(self, claim):
        body = claim.get("claim_text") or claim.get("text") or ""
        return {"claim_id": short_label(claim.get("claim_id")), "body_chars": len(body),
                "body_sha256": body_hash(body),
                "verification_status": short_label(claim.get("verification_status")),
                "reason": self.safe_text(claim.get("reason")),
                "evidence_ids": [short_label(eid) for eid in claim.get("evidence_ids") or []]}

    def manual_summary(self, manual):
        allowed = ("schema_version", "scope", "claim_ids", "target_claim_ids", "baseline_source", "baseline_status",
                   "applied", "text_applied", "application_status", "verification_status", "hypothesis_review_status",
                   "changed_claim_ids", "revised_claim_ids", "unchanged_requested_claim_ids", "missing_requested_claim_ids")
        result = {key: manual.get(key) for key in allowed if key in manual}
        result["notes_chars"] = len(manual.get("notes") or "")
        result["targets"] = [{key: target.get(key) for key in (
            "claim_id", "baseline_hash", "current_hash", "status", "verification_status")}
            for target in manual.get("targets") or [] if isinstance(target, dict)]
        result["revision_event_count"] = len(manual.get("revision_events") or [])
        return result

    def snapshot(self, full):
        state = full.get("state_json") or {}
        claims = state.get("claims") or []
        manual = state.get("manual_review_request") or {}
        target_ids = set(manual.get("target_claim_ids") or manual.get("claim_ids") or [])
        automatic = [claim for claim in claims if claim.get("claim_id") not in target_ids]
        retrieval = state.get("science_retrieval") or {}
        report = state.get("final_report") or full.get("final_report") or ""
        return {"observed_at": now(), "session_id": full.get("session_id"),
                "status": short_label(full.get("status")), "phase": short_label(state.get("phase")),
                "outcome": short_label(state.get("outcome")), "review_verdict": short_label(state.get("review_verdict")),
                "stop_reason": short_label(state.get("stop_reason")),
                "quality_review_status": short_label(state.get("quality_review_status")),
                "quality_score": safe_counter(state.get("quality_score")),
                "iteration": safe_counter(state.get("iteration")), "max_iterations": safe_counter(state.get("max_iterations")),
                "review_extension_rounds": safe_counter(state.get("review_extension_rounds")),
                "manual": self.manual_summary(manual),
                "automatic_claim_status_counts": dict(Counter(str(c.get("verification_status")) for c in automatic)),
                "claim_status_counts": dict(Counter(str(c.get("verification_status")) for c in claims)),
                "claims": [self.claim_summary(claim) for claim in claims],
                "agent_models": {key: short_label(value) for key, value in
                                 (state.get("research_profile") or {}).get("agent_models", {}).items()},
                "papers_count": len(state.get("papers") or []), "evidence_count": len(state.get("evidence_ledger") or {}),
                "charts_count": len(state.get("charts") or []), "history_count": len(state.get("review_history") or []),
                "report_chars": len(report), "report_sha256": body_hash(report),
                "retrieval_usage": {key: safe_counter(retrieval.get(key)) for key in
                                    ("requests_used", "documents_used", "elapsed_seconds", "batches_started")},
                "checkpoint_digest": checkpoint_digest(full)}

    def save(self):
        self.results["updated_at"] = now()
        write_private_json(RESULT, self.results)

    def store_snapshot(self, full):
        summary = self.snapshot(full)
        entry = self.results["sessions"].setdefault(full["session_id"], {"samples": []})
        entry["samples"].append(summary)
        entry["latest"] = summary
        self.current["snapshot"] = summary
        self.save()
        return summary

    async def micro(self):
        owner = self.authenticated("owner")
        before = self.owned_checkpoint(owner, OLD_SESSION)
        before_digest = checkpoint_digest(before)
        state = deepcopy(before.get("state_json") or {})
        by_id = {claim.get("claim_id"): claim for claim in state.get("claims") or []}
        self.require("three fixed historical counterexamples are present", all(cid in by_id for _, cid in MICRO_CASES))
        selected = [deepcopy(by_id[cid]) for _, cid in MICRO_CASES]
        self.current.update(source_session_id=OLD_SESSION, old_checkpoint_digest_before=before_digest,
                            sample_transforms=["deepcopy_only", "three_selected_claims", "manual_request_and_history_removed_in_memory",
                                               "iteration_equals_max_in_memory"],
                            before_claims=[{"case": name, **self.claim_summary(by_id[cid])} for name, cid in MICRO_CASES])
        state.update(claims=selected, manual_review_request={}, review_history=[], review_contract_audit=[],
                     phase="reviewing", iteration=3, max_iterations=3)
        from config.llm_config import get_config
        from service.deep_research_v2.agents.critic import CriticMaster

        config = get_config()
        critic = CriticMaster(config.api_key, config.base_url, "qwen-plus")
        critic.client = critic.client.with_options(timeout=90, max_retries=0)
        critic.cache_scope = None
        call_count = 0
        real_call = critic.call_llm

        async def count_real_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return await real_call(*args, **kwargs)

        critic.call_llm = count_real_call
        started = time.monotonic()
        try:
            await asyncio.wait_for(critic.process(state), timeout=480)
        finally:
            critic.client.close()
            after = self.owned_checkpoint(owner, OLD_SESSION)
            unchanged = before_digest == checkpoint_digest(after)
            self.current.update(model="qwen-plus", model_call_count=call_count,
                                elapsed_seconds=round(time.monotonic() - started, 3),
                                old_checkpoint_digest_after=checkpoint_digest(after), old_checkpoint_unchanged=unchanged)
            self.check("historical checkpoint was not mutated", unchanged)
            self.save()
        rows = {row.get("claim_id"): row for row in (state.get("claim_verification") or {}).get("results") or []}
        self.current["review_contract_audit"] = [{"version": item.get("version"), "iteration": item.get("iteration"),
            "attempts": [{"attempt": attempt.get("attempt"), "claim_ids": attempt.get("claim_ids") or [],
                          "violations": attempt.get("violations") or {}} for attempt in item.get("attempts") or []]}
            for item in state.get("review_contract_audit") or []]
        self.current["after_claims"] = [{"case": name, **self.claim_summary(next(c for c in state["claims"] if c["claim_id"] == cid)),
                                         "reason_code": short_label(rows.get(cid, {}).get("reason_code")),
                                         "scope_errors": rows.get(cid, {}).get("scope_errors") or [],
                                         "contract_errors": rows.get(cid, {}).get("contract_errors") or [],
                                         "evidence_checks": [{"evidence_id": short_label(check.get("evidence_id")),
                                                              "relation": short_label(check.get("relation")),
                                                              "reason": self.safe_text(check.get("reason"), 350)}
                                                             for check in rows.get(cid, {}).get("evidence_checks") or []]}
                                        for name, cid in MICRO_CASES]
        statuses = {claim["claim_id"]: claim.get("verification_status") for claim in state["claims"]}
        self.check("old readable chunk is now substantively evaluated",
                   statuses[MICRO_CASES[0][1]] in {"supported", "insufficient", "contradicted"})
        self.check("field-wide absence is not accepted from sampled evidence", statuses[MICRO_CASES[1][1]] == "insufficient")
        self.check("bounded synthetic statement remains supported", statuses[MICRO_CASES[2][1]] == "supported")
        self.current["micro_quality_counts"] = dict(Counter(statuses.values()))
        self.current["not_a_formal_quality_metric"] = True

    def consume(self, client, endpoint, body, session_id):
        started, counts, phases = time.monotonic(), Counter(), []
        complete, stream_errors = False, []
        self.current.update(session_id=session_id, sse_started_at=now())
        self.save()
        try:
            with client.stream("POST", endpoint, json=body,
                               timeout=httpx.Timeout(120, connect=10, write=30, pool=30)) as response:
                self.require("ordinary research SSE accepted", response.status_code == 200, status=response.status_code)
                for line in response.iter_lines():
                    if time.monotonic() - started > 1200:
                        raise TimeoutError("Acceptance stream exceeded 20-minute wall-clock allowance; connection closed")
                    if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                        continue
                    event = json.loads(line[5:].strip())
                    kind = short_label(event.get("type")) or "unknown"
                    counts[kind] += 1
                    if kind == "phase":
                        phase = short_label(event.get("phase"))
                        if phase is None and isinstance(event.get("content"), dict):
                            phase = short_label(event["content"].get("phase"))
                        phases.append(phase)
                        print(json.dumps({"observed_at": now(), "session_id": session_id,
                                          "event": "phase", "phase": phase}, ensure_ascii=False), flush=True)
                    if kind == "error":
                        stream_errors.append({"event": kind, "code": short_label(event.get("code"))})
                    if kind in {"research_complete", "complete"}:
                        complete = True
        finally:
            self.current.update(event_counts=dict(counts), phases=phases, complete_event_received=complete,
                                stream_errors=stream_errors, stream_seconds=round(time.monotonic() - started, 3))
            self.save()
        self.check("research stream emitted completion", complete)
        self.check("research stream emitted no errors", not stream_errors)

    def run(self):
        owner = self.authenticated("owner")
        old = self.owned_checkpoint(owner, OLD_SESSION)
        self.current["old_checkpoint_digest_before"] = checkpoint_digest(old)
        response = self.request(owner, "create isolated quality research", "POST", "/sessions", expected=201,
                                json={"title": "科研审核质量与人工状态复验 · 20261015", "session_type": "deepsearch"})
        sid = str(UUID(response.json()["id"]))
        self.require("new run is separate from old L2", sid != OLD_SESSION)
        self.results["latest_session_id"] = sid
        self.results["sessions"].setdefault(sid, {"samples": []})["created_at"] = now()
        self.current["session_id"] = sid
        self.save()
        print(json.dumps({"observed_at": now(), "session_id": sid, "event": "new_scoped_run_created"}), flush=True)
        self.request(owner, "save isolated user question", "POST", f"/sessions/{sid}/messages", expected=201,
                     json={"role": "user", "content": QUERY})
        resources = self.resources()
        body = {"query": QUERY, "session_id": sid, "version": "v2", "profile_id": "science",
                "search_web": False, "search_local": True, "kb_name": resources["knowledge_base_name"],
                "max_iterations": 1}
        self.consume(owner, "/research/stream", body, sid)
        full = self.owned_checkpoint(owner, sid)
        state = full.get("state_json") or {}
        self.check("new local run reached a terminal checkpoint", full.get("status") == "completed")
        self.check("new run uses the scoped existing knowledge base",
                   state.get("knowledge_base_id") == resources["knowledge_base_id"]
                   and state.get("search_local") is True and state.get("search_web") is False)
        self.check("new run has actual authored claims", bool(state.get("claims")))
        self.store_snapshot(full)
        after = self.owned_checkpoint(owner, OLD_SESSION)
        self.current["old_checkpoint_digest_after"] = checkpoint_digest(after)
        self.check("old L2 unchanged after independent new run", checkpoint_digest(old) == checkpoint_digest(after))

    def manual(self, session_id, target):
        owner = self.authenticated("owner")
        sid = str(UUID(session_id))
        self.require("manual only targets a run created by this script", sid in self.results.get("sessions", {}) and sid != OLD_SESSION)
        before = self.owned_checkpoint(owner, sid)
        self.require("manual recheck starts from completed run", before.get("status") == "completed")
        claims = before.get("state_json", {}).get("claims") or []
        old_claim = next((claim for claim in claims if claim.get("claim_id") == target), None)
        self.require("manual target exists in the new run", old_claim is not None)
        self.current.update(session_id=sid, target_claim_id=target, before_target=self.claim_summary(old_claim),
                            baseline_checkpoint_digest=checkpoint_digest(before))
        self.save()
        self.consume(owner, f"/research/resume/{sid}", {"additional_iterations": 1,
                     "review_notes": MANUAL_NOTES, "review_claim_ids": [target]}, sid)
        after = self.owned_checkpoint(owner, sid)
        summary = self.store_snapshot(after)
        state = after.get("state_json") or {}
        manual = state.get("manual_review_request") or {}
        new_claim = next((claim for claim in state.get("claims") or [] if claim.get("claim_id") == target), None)
        self.require("manual target identity is retained", new_claim is not None)
        self.current["after_target"] = self.claim_summary(new_claim)
        changed = body_hash(old_claim.get("claim_text")) != body_hash(new_claim.get("claim_text"))
        self.check("requested target body actually changed", changed)
        self.check("manual application tracks only its specified target",
                   manual.get("applied") is True and manual.get("text_applied") is True
                   and manual.get("target_claim_ids") == [target] and target in (manual.get("changed_claim_ids") or []))
        self.check("target baseline equals the actual pre-request body",
                   any(row.get("claim_id") == target and row.get("baseline_hash") == body_hash(old_claim.get("claim_text"))
                       for row in manual.get("targets") or []))
        self.check("selected manual request does not require global hypotheses", manual.get("hypothesis_review_status") == "not_requested")
        self.check("manual received exactly its explicit one-round extension",
                   state.get("review_extension_rounds", 0) == before["state_json"].get("review_extension_rounds", 0) + 1)
        self.current["independent_disposition"] = {"manual_applied": manual.get("applied"),
            "manual_verification_status": short_label(manual.get("verification_status")),
            "target_verification_status": short_label(new_claim.get("verification_status")),
            "automatic_claim_status_counts": summary["automatic_claim_status_counts"],
            "overall_review_verdict": summary["review_verdict"], "overall_quality_review_status": summary["quality_review_status"]}

    def collect(self, session_id):
        owner = self.read_only_owner()
        sid = str(UUID(session_id))
        full = self.owned_checkpoint(owner, sid)
        self.current["session_id"] = sid
        self.store_snapshot(full)

    def migration(self):
        """Replay the exact legacy request in memory; never rewrite its history."""
        owner = self.read_only_owner()
        before = self.owned_checkpoint(owner, OLD_SESSION)
        old_state = before.get("state_json") or {}
        state = deepcopy(old_state)
        manual = state.get("manual_review_request") or {}
        self.require("old L2 retains the unapplied legacy manual request",
                     bool(manual.get("notes")) and manual.get("applied") is False)
        old_digest = checkpoint_digest(before)
        nonmanual_before = digest({key: value for key, value in state.items() if key != "manual_review_request"})
        from service.deep_research_v2.manual_review import initialize_manual_review, update_manual_progress

        initialize_manual_review(state, manual)
        update_manual_progress(state, manual)
        target_ids = set(manual.get("target_claim_ids") or [])
        claim_map = {claim.get("claim_id"): claim for claim in state.get("claims") or []}
        targets = [{"claim_id": target.get("claim_id"),
                    "baseline_chars": len(target.get("baseline_text") or ""),
                    "current_chars": len((claim_map.get(target.get("claim_id")) or {}).get("claim_text") or ""),
                    "baseline_hash": target.get("baseline_hash"), "current_hash": target.get("current_hash"),
                    "status": short_label(target.get("status"))}
                   for target in manual.get("targets") or []]
        nonmanual_after = digest({key: value for key, value in state.items() if key != "manual_review_request"})
        automatic_counts = dict(Counter(str(claim.get("verification_status"))
                                       for claim in state.get("claims") or [] if claim.get("claim_id") not in target_ids))
        self.check("legacy baseline recovered from original review history",
                   manual.get("baseline_source") == "review_history" and manual.get("baseline_status") == "recovered")
        self.check("known 127 to 118 character edit is recovered without Writer execution",
                   len(targets) == 1 and targets[0]["claim_id"] == "claim_5b130654dc4ca204"
                   and targets[0]["baseline_chars"] == 127 and targets[0]["current_chars"] == 118
                   and targets[0]["baseline_hash"] != targets[0]["current_hash"] and targets[0]["status"] == "changed")
        self.check("manual edit application is independent of remaining automatic issues",
                   manual.get("applied") is True and manual.get("text_applied") is True
                   and bool(automatic_counts.get("insufficient", 0) or automatic_counts.get("unverified", 0)))
        self.check("all nonmanual state including claims quality outcome and budgets stays unchanged",
                   nonmanual_before == nonmanual_after)
        after = self.owned_checkpoint(owner, OLD_SESSION)
        unchanged = old_digest == checkpoint_digest(after)
        self.check("legacy checkpoint is unchanged after read-only migration replay", unchanged)
        self.current.update(source_session_id=OLD_SESSION, migration_replay=True, writer_executed=False,
                            model_call_count=0, task_writes=0, old_checkpoint_unchanged=unchanged,
                            old_checkpoint_digest_before=old_digest, old_checkpoint_digest_after=checkpoint_digest(after),
                            before_applied=old_state.get("manual_review_request", {}).get("applied"),
                            after_applied=manual.get("applied"), before_manual=self.manual_summary(old_state.get("manual_review_request") or {}),
                            after_manual=self.manual_summary(manual), targets=targets,
                            nonmanual_state_digest_before=nonmanual_before, nonmanual_state_digest_after=nonmanual_after,
                            preserved_state={"automatic_claim_status_counts": automatic_counts,
                                             **{key: old_state.get(key) for key in ("quality_review_status", "review_verdict", "outcome", "stop_reason",
                                                                                   "iteration", "max_iterations", "review_extension_rounds")},
                                             "retrieval_usage": {key: safe_counter((old_state.get("science_retrieval") or {}).get(key))
                                                                 for key in ("requests_used", "documents_used", "elapsed_seconds", "batches_started")}})

    def finish(self, error=None):
        if error is not None:
            self.check("command completed without exception", False, error_type=type(error).__name__, error=self.safe_text(error))
        for client in self.clients:
            client.close()
        failed = [row for row in self.checks if not row["passed"]]
        self.current.update(finished_at=now(), checks=self.checks,
                            passed=len(self.checks) - len(failed), total=len(self.checks), failed=len(failed))
        self.results["runs"].append(self.current)
        self.save()
        public = {key: self.current.get(key) for key in ("command", "session_id", "source_session_id", "model",
                  "model_call_count", "elapsed_seconds", "old_checkpoint_unchanged", "migration_replay",
                  "writer_executed", "task_writes", "before_applied", "after_applied", "passed", "total", "failed") if key in self.current}
        public["artifact"] = str(RESULT.relative_to(RUNTIME.parent.parent.parent))
        if self.current.get("snapshot"):
            public["snapshot"] = {key: self.current["snapshot"][key] for key in (
                "status", "phase", "outcome", "review_verdict", "quality_review_status", "claim_status_counts", "manual")}
        if self.current.get("after_claims"):
            public["micro_results"] = [{key: claim.get(key) for key in ("case", "claim_id", "verification_status", "reason_code", "scope_errors", "contract_errors")}
                                       for claim in self.current["after_claims"]]
        if failed:
            public["failures"] = failed
        print(json.dumps(public, ensure_ascii=False, allow_nan=False), flush=True)
        return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("micro", "run"):
        item = sub.add_parser(name)
        item.add_argument("--execute", action="store_true", help="Explicitly allow real provider calls and scoped new-run writes")
    manual = sub.add_parser("manual")
    manual.add_argument("--execute", action="store_true")
    manual.add_argument("session_id", type=str)
    manual.add_argument("--target", required=True, type=str)
    collect = sub.add_parser("collect")
    collect.add_argument("session_id", type=str)
    sub.add_parser("migration", help="GET old L2 and replay legacy manual migration only in memory; no model or task writes")
    sub.add_parser("selfcheck", help="Pure offline serializer check; no credentials, files or network")
    args = parser.parse_args()
    if args.command == "selfcheck":
        return selfcheck()
    if args.command not in {"collect", "migration"} and not args.execute:
        parser.error("Real execution requires --execute")
    if hasattr(args, "session_id"):
        try:
            UUID(args.session_id)
        except ValueError:
            parser.error("session_id must be a UUID")
    if args.command == "manual" and not re.fullmatch(r"claim_[0-9a-f]{16}", args.target):
        parser.error("--target must be an actual claim_<16 hex> ID from the new run")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    acceptance = ReviewQualityAcceptance(args.command)
    try:
        if args.command == "micro":
            asyncio.run(acceptance.micro())
        elif args.command == "run":
            acceptance.run()
        elif args.command == "manual":
            acceptance.manual(args.session_id, args.target)
        elif args.command == "migration":
            acceptance.migration()
        else:
            acceptance.collect(args.session_id)
    except Exception as error:
        return acceptance.finish(error)
    return acceptance.finish()


def selfcheck():
    secret = "SYNTHETIC_SECRET_MUST_NOT_APPEAR"
    instance = ReviewQualityAcceptance.__new__(ReviewQualityAcceptance)
    instance.redact = lambda value: str(value or "").replace(secret, "[REDACTED]")
    manual = {"notes": secret, "applied": True, "text_applied": True, "scope": "selected_claims",
              "target_claim_ids": ["claim_0123456789abcdef"], "verification_status": "insufficient",
              "targets": [{"claim_id": "claim_0123456789abcdef", "baseline_text": secret,
                           "baseline_hash": body_hash(secret), "current_hash": body_hash("changed"), "status": "changed"}]}
    state = {"claims": [{"claim_id": "claim_0123456789abcdef", "claim_text": secret,
                         "verification_status": "insufficient", "reason": "See https://invalid.example/?token=" + secret}],
             "manual_review_request": manual, "final_report": secret, "outcome": "completed_with_warnings",
             "review_verdict": "needs_revision", "quality_review_status": "confirmed"}
    sample = instance.snapshot({"session_id": OLD_SESSION, "status": "completed", "state_json": state})
    encoded = json.dumps(sample, ensure_ascii=False)
    assert secret not in encoded and "https://" not in encoded and "baseline_text" not in encoded
    assert sample["manual"]["applied"] is True and sample["manual"]["verification_status"] == "insufficient"
    assert sample["review_verdict"] == "needs_revision" and sample["claim_status_counts"] == {"insufficient": 1}
    assert not sample["automatic_claim_status_counts"]
    assert all(re.fullmatch(r"claim_[0-9a-f]{16}", cid) for _, cid in MICRO_CASES)
    print(json.dumps({"command": "selfcheck", "passed": True, "credentials_read": False,
                      "network_calls": 0, "files_written": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
