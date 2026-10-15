"""Offline behavioral regressions. These do NOT measure research quality metrics."""
import asyncio
import copy
import json
import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace
from fastapi import HTTPException
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "app"))
from config.research_profiles import get_research_profile
from service.deep_research_v2.evidence import (register_evidence, ensure_science_state, normalize_paragraph,
                                               references_from_ledger, render_science_report, validate_citations)
from service.deep_research_v2.science_roles import (assess_evidence, corpus_analysis, visualize_science,
                                                  analyze_science, review_science, scout_science,
                                                  classify_research_gaps, research_scope, plan_science, revise_science,
                                                  review_hypotheses_with_notes)
from service.deep_research_v2.state import create_initial_state
from service.deep_research_v2.graph import DeepResearchGraph
from service.deep_research_v2.agents.critic import CriticMaster
from service.deep_research_v2.manual_review import initialize_manual_review
from router.research_router import ResumeResearchRequest, _prepare_bounded_recheck, resume_research
research_router_module = importlib.import_module("router.research_router")


def fixture_state(minimum=2):
    state = create_initial_state("2020-2026年科学研究问题", "science_test", search_web=True)
    state["research_profile"] = get_research_profile("science", minimum)
    state["outline"] = [{"id": "sec_1", "title": "方法", "status": "pending"}]
    ensure_science_state(state)
    return state


def paper(i, **overrides):
    result = {"title": f"Actual fixture paper {i}", "doi": f"10.0000/fixture{i}",
              "url": f"https://example.org/paper/{i}", "year": 2020 + i % 7,
              "abstract": "A siamese convolution network is examined. " * 6,
              "verified": True, "authors": ["Test Author"], "provider": "fixture", "evidence_level": "abstract"}
    result.update(overrides)
    return result


def add_papers(state, count=3):
    state["papers"] = [register_evidence(state, paper(i)) for i in range(count)]


def agent():
    result = Mock()
    result.name = "TestAgent"
    result.logger = Mock()
    result._weighted_score = CriticMaster._weighted_score
    result.SCORE_WEIGHTS = CriticMaster.SCORE_WEIGHTS
    return result


def review_result(claim, status="supported", reason="fixture evidence check"):
    relation = {"supported": "supports", "contradicted": "contradicts", "insufficient": "insufficient", "unverified": "insufficient"}[status]
    return {"claim_id": claim["claim_id"], "status": status, "reason": reason,
            "reason_code": "semantic_uncertain" if status == "unverified" else "content_checked",
            "evidence_checks": [{"evidence_id": eid, "relation": relation, "reason": reason} for eid in claim["evidence_ids"]]}


class EvidenceTests(unittest.TestCase):
    def test_profile_snapshot_isolation(self):
        first = get_research_profile("science")
        first["agent_models"]["writer"] = "changed"
        self.assertNotEqual(first["agent_models"], get_research_profile("science")["agent_models"])
        self.assertEqual(get_research_profile("remote_sensing")["mode"], "science")

    def test_doi_identity_normalization_and_local_chunk_identity(self):
        state = fixture_state()
        first = register_evidence(state, paper(1))
        same = register_evidence(state, paper(1, doi="https://doi.org/10.0000/FIXTURE1"))
        self.assertEqual(first["evidence_id"], same["evidence_id"])
        a = register_evidence(state, paper(1, document_id="doc1", chunk_id="c1"), local=True)
        b = register_evidence(state, paper(1, document_id="doc2", chunk_id="c1"), local=True)
        c = register_evidence(state, paper(1, document_id="doc1", chunk_id="c2"), local=True)
        self.assertNotEqual(a["source_id"], b["source_id"])
        self.assertNotEqual(a["evidence_id"], c["evidence_id"])
        self.assertEqual(a["source_id"], c["source_id"])

    def test_server_citations_reject_unknown_sources(self):
        state = fixture_state()
        known = register_evidence(state, paper(1))
        claim = normalize_paragraph(state, "Text [fake](https://fake.test).", [known["evidence_id"], "forged"], "sec_1", 0)
        self.assertNotIn("fake.test", claim["claim_text"])
        self.assertEqual(claim["evidence_ids"], [known["evidence_id"]])
        state["claims"] = [claim]
        self.assertEqual(validate_citations(state), [])
        state["claims"][0]["evidence_ids"].append("unknown")
        self.assertEqual(len(validate_citations(state)), 1)

    def test_real_demo_internal_evidence_markers_do_not_leak_into_report(self):
        state = fixture_state()
        known = register_evidence(state, paper(1))
        claim = normalize_paragraph(state,
            "本综述分析方法机制 [ev_6488353dc8c6ca18]，保留实验局限。"
            " [ev_123abc, ev_456def] `ev_789abc` [3] F1 与 IoU 需按口径比较。",
            [known["evidence_id"]], "sec_1", 0)
        self.assertNotIn("ev_", claim["claim_text"])
        self.assertNotIn("[3]", claim["claim_text"])
        self.assertIn("F1 与 IoU", claim["claim_text"])
        self.assertEqual(claim["evidence_ids"], [known["evidence_id"]])
        state.update(science_sections=[{"id": "sec_1", "title": "方法"}], claims=[claim])
        report = render_science_report(state)
        self.assertNotIn("ev_", report)
        self.assertIn("](https://example.org/paper/1)", report)

    def test_optional_metrics_hypotheses_and_out_of_range_baselines_are_limitations(self):
        query = "围绕2020-2026年光学遥感图像变化检测方法开展文献调研，生成文献综述。"
        critical, limitations, searches = classify_research_gaps({"critical_gaps": [
            {"kind": "topic_coverage", "description": "缺乏跨方法可比F1和IoU数字", "user_requirement_quote": "光学遥感图像变化检测方法"},
            {"kind": "topic_coverage", "description": "缺少2020年前基线对比", "user_requirement_quote": "2020-2026"},
            {"kind": "hypothesis", "description": "假设尚未证实", "user_requirement_quote": "文献综述"},
            "只有自由文本而没有明确用户需求依据的缺口",
        ]}, query)
        self.assertEqual(critical, [])
        self.assertEqual(searches, [])
        self.assertEqual(len(limitations), 4)
        self.assertFalse(research_scope(query)["requires_quantitative_comparison"])

    def test_explicit_topic_and_quantitative_requirements_still_trigger_gaps(self):
        query = "比较光学遥感变化检测在LEVIR数据集的F1性能排名。"
        critical, _, queries = classify_research_gaps({"critical_gaps": [
            {"kind": "required_comparison", "description": "缺少相同划分的F1数值", "user_requirement_quote": "F1性能排名",
             "search_queries": ["LEVIR change detection F1 benchmark"]},
            {"kind": "topic_coverage", "description": "没有光学遥感资料", "user_requirement_quote": "光学遥感变化检测",
             "search_queries": ["optical remote sensing change detection"]},
            {"kind": "topic_coverage", "description": "用户未要求的医学证据", "user_requirement_quote": "医学研究"},
        ]}, query)
        self.assertEqual(len(critical), 2)
        self.assertEqual(len(queries), 2)

    def test_metadata_only_is_not_content_evidence(self):
        state = fixture_state(1)
        p = register_evidence(state, paper(1, abstract="", content="A long title " * 20, evidence_level="metadata"))
        state["papers"] = [p]
        self.assertFalse(assess_evidence(state)["sufficient"])

    def test_corpus_graph_and_chart_values_have_provenance(self):
        state = fixture_state()
        add_papers(state, 10)
        stats = corpus_analysis(state)
        self.assertEqual(sum(stats["year_distribution"].values()), 10)
        self.assertEqual(stats["method_mentions"]["孪生网络"], 10)
        ids = {n["id"] for n in state["knowledge_graph"]["nodes"]}
        self.assertTrue(all(e["source"] in ids and e["target"] in ids for e in state["knowledge_graph"]["edges"]))
        self.assertEqual(len(references_from_ledger(state)), 10)

    def test_report_contains_complete_bibliography_without_fabricated_numbers(self):
        state = fixture_state()
        add_papers(state, 65)
        corpus_analysis(state)
        state["science_sections"] = [{"id": "sec_1", "title": "结论"}]
        state["claims"] = [normalize_paragraph(state, "Evidence-bound conclusion.", [state["papers"][0]["evidence_id"]], "sec_1", 0)]
        report = render_science_report(state)
        self.assertEqual(len(state["references"]), 65)
        self.assertIn("65 篇", report)
        self.assertIn("fixture64", report)
        self.assertNotIn("local://", report)
        self.assertIn("按年份均衡取样并优先保留可读摘要", report)


class BoundedRecheckTests(unittest.TestCase):
    def completed(self, supported=False):
        state = fixture_state(1)
        add_papers(state, 1)
        assess_evidence(state)
        claim = normalize_paragraph(state, "作者报告定性改善。", [state["papers"][0]["evidence_id"]], "sec_1", 0)
        claim["verification_status"] = "supported" if supported else "insufficient"
        state.update(phase="completed", iteration=3, max_iterations=3, final_report="Original report",
                     claims=[claim], quality_score=10 if supported else 6.0,
                     quality_review_status="confirmed", unresolved_issues=0 if supported else 1)
        return {"status": "completed", "state_json": state, "ui_state_json": {"streaming_report": "Original report"}}

    def test_explicit_extension_archives_original_and_preserves_verdict(self):
        full = self.completed()
        before = copy.deepcopy(full)
        state, recheck = _prepare_bounded_recheck(full, ResumeResearchRequest(additional_iterations=1))
        self.assertTrue(recheck)
        self.assertEqual(full, before)
        self.assertEqual(state["_next_step"], "reviewing")
        self.assertEqual(state["max_iterations"], 4)
        self.assertEqual(state["review_extension_rounds"], 1)
        self.assertEqual(state["review_history"][0]["state"], before["state_json"])
        self.assertEqual(state["quality_score"], 6.0)
        self.assertEqual(state["claims"][0]["verification_status"], "insufficient")

    def test_completed_requires_explicit_budget_and_passed_report_cannot_reopen(self):
        for full, request in [(self.completed(), None), (self.completed(True), ResumeResearchRequest(additional_iterations=1))]:
            with self.assertRaises(HTTPException) as error:
                _prepare_bounded_recheck(full, request)
            self.assertEqual(error.exception.status_code, 400)

    def test_lifetime_extension_limit_survives_repeated_completion(self):
        full = self.completed()
        first, _ = _prepare_bounded_recheck(full, ResumeResearchRequest(additional_iterations=1))
        first.update(phase="completed", iteration=4)
        full["state_json"] = first
        second, _ = _prepare_bounded_recheck(full, ResumeResearchRequest(additional_iterations=1))
        self.assertEqual(second["review_extension_rounds"], 2)
        self.assertEqual(len(second["review_history"]), 2)
        self.assertNotIn("review_history", second["review_history"][1]["state"])
        full["state_json"] = second
        with self.assertRaises(HTTPException):
            _prepare_bounded_recheck(full, ResumeResearchRequest(additional_iterations=1))
        for invalid in (0, 3, -1):
            with self.assertRaises(ValidationError):
                ResumeResearchRequest(additional_iterations=invalid)

    def test_paused_research_resumes_without_gaining_budget(self):
        full = self.completed()
        full["status"] = "paused"
        full["state_json"].update(phase="reviewing", _next_step="reviewing")
        state, recheck = _prepare_bounded_recheck(full, None)
        self.assertFalse(recheck)
        self.assertEqual(state, full["state_json"])
        with self.assertRaises(HTTPException):
            _prepare_bounded_recheck(full, ResumeResearchRequest(additional_iterations=1))

    def test_manual_notes_are_archived_and_consume_one_explicit_revision_round(self):
        full = self.completed(True)
        cid = full["state_json"]["claims"][0]["claim_id"]
        request = ResumeResearchRequest(additional_iterations=1, review_notes="核对原文限定条件，不能扩大为领域事实", review_claim_ids=[cid])
        state, recheck = _prepare_bounded_recheck(full, request)
        self.assertTrue(recheck)
        self.assertEqual(state["iteration"], 4)
        self.assertEqual(state["max_iterations"], 4)
        self.assertEqual(state["phase"], "revising")
        self.assertEqual(state["review_history"][0]["review_notes"], request.review_notes)
        self.assertEqual(state["manual_review_request"]["claim_ids"], [cid])
        self.assertEqual(state["claims"][0]["verification_status"], "supported")
        with self.assertRaises(HTTPException):
            _prepare_bounded_recheck(full, ResumeResearchRequest(additional_iterations=1, review_notes="核对", review_claim_ids=["unknown"]))
        with self.assertRaises(ValidationError):
            ResumeResearchRequest(additional_iterations=1, review_notes="x" * 4001)

    def test_remaining_previously_granted_round_is_reused_without_new_budget(self):
        full = self.completed(True)
        cid = full["state_json"]["claims"][0]["claim_id"]
        first, _ = _prepare_bounded_recheck(full, ResumeResearchRequest(additional_iterations=2, review_notes="首次定向复核", review_claim_ids=[cid]))
        first["phase"] = "completed"
        full["state_json"] = first
        self.assertEqual((first["iteration"], first["max_iterations"]), (4, 5))
        request = ResumeResearchRequest(use_remaining_budget=True, review_notes="仍有待修正的具体问题", review_claim_ids=[cid])
        second, _ = _prepare_bounded_recheck(full, request)
        self.assertEqual((second["iteration"], second["max_iterations"], second["review_extension_rounds"]), (5, 5, 2))
        self.assertTrue(second["review_history"][-1]["used_existing_budget"])
        self.assertEqual(second["review_history"][-1]["additional_iterations"], 0)
        self.assertEqual(second["review_history"][-1]["remaining_budget_before"], 1)
        full["state_json"] = second
        with self.assertRaises(HTTPException):
            _prepare_bounded_recheck(full, request)
        with self.assertRaises(HTTPException):
            _prepare_bounded_recheck(full, ResumeResearchRequest(use_remaining_budget=True))
        with self.assertRaises(HTTPException):
            _prepare_bounded_recheck(full, ResumeResearchRequest(use_remaining_budget=True, additional_iterations=1, review_notes="复核"))


class AsyncBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_global_manual_review_uses_model_revision_and_rechecks_hypothesis_reason(self):
        state = fixture_state(1)
        add_papers(state, 1)
        eid = state["papers"][0]["evidence_id"]
        claims = [normalize_paragraph(state, "原段落" + str(i), [eid], "sec_1", i) for i in range(3)]
        for c in claims:
            c["verification_status"] = "supported"
        claims[2]["verification_status"] = "insufficient"
        state.update(claims=claims, science_sections=[{"id": "sec_1", "title": "方法"}],
                     hypotheses=[{"id": "hyp_1", "content": "比较不同路线", "status": "supported", "reason": "待纠正的谱系外推", "evidence_ids": [eid]}],
                     manual_review_request={"notes": "全局核对谱系、年份与作者限定，包括假设理由", "claim_ids": [], "applied": False})
        initialize_manual_review(state, state["manual_review_request"], new_request=True)
        responses = [{"revisions": [{"claim_id": claims[i]["claim_id"], "text": "模型基于证据修订" + str(i), "evidence_ids": [eid]} for i in range(3)]},
                     {"hypotheses": [{"id": "hyp_1", "status": "insufficient", "reason": "来源未支持该谱系关系", "evidence_ids": [eid],
                                       "evidence_checks": [{"evidence_id": eid, "year": 2020, "method": "siamese network", "relation": "contradicts"}]}]}]
        with patch("service.deep_research_v2.science_roles.json_call", new_callable=AsyncMock, side_effect=responses) as call:
            await revise_science(agent(), state)
        self.assertEqual(call.await_count, 2)
        self.assertIn("人工复核意见", call.call_args_list[0].args[1])
        self.assertIn("原有reason是待复核草稿", call.call_args_list[1].args[1])
        self.assertEqual(state["claims"][1]["claim_text"], "模型基于证据修订1")
        self.assertEqual(state["claims"][0]["claim_text"], "模型基于证据修订0")
        self.assertEqual(state["claims"][0]["verification_status"], "pending")
        self.assertEqual(state["hypotheses"][0]["reason"], "来源未支持该谱系关系")
        self.assertTrue(state["manual_review_request"]["applied"])
        self.assertEqual(state["manual_review_request"]["hypothesis_review_status"], "confirmed")
        self.assertEqual(state["phase"], "reviewing")

    async def test_hypothesis_wrong_year_or_background_support_is_not_confirmed(self):
        for year, relation in ((2025, "supports"), (2020, "background")):
            state = fixture_state(1)
            add_papers(state, 1)
            eid = state["papers"][0]["evidence_id"]
            state["hypotheses"] = [{"id": "hyp_1", "content": "检验主方法", "evidence_ids": [eid]}]
            manual = {"notes": "核对主方法与年份"}
            response = {"hypotheses": [{"id": "hyp_1", "status": "supported", "reason": "错误映射的候选理由", "evidence_ids": [eid],
                "evidence_checks": [{"evidence_id": eid, "year": year, "method": "different architecture", "relation": relation}]}]}
            with patch("service.deep_research_v2.science_roles.json_call", new_callable=AsyncMock, return_value=response):
                confirmed = await review_hypotheses_with_notes(agent(), state, manual)
            self.assertFalse(confirmed)
            self.assertEqual(state["hypotheses"][0]["status"], "insufficient")
            self.assertEqual(state["hypotheses"][0]["evidence_ids"], [])

    async def test_unchanged_manually_requested_claim_is_not_marked_applied(self):
        state = fixture_state(1)
        add_papers(state, 1)
        eid = state["papers"][0]["evidence_id"]
        claim = normalize_paragraph(state, "未经证明的首次引入断言", [eid], "sec_1", 0)
        claim["verification_status"] = "supported"
        state.update(claims=[claim], science_sections=[{"id": "sec_1", "title": "方法"}],
                     manual_review_request={"notes": "收窄为样本年代", "claim_ids": [claim["claim_id"]], "applied": False})
        initialize_manual_review(state, state["manual_review_request"], new_request=True)
        response = {"revisions": [{"claim_id": claim["claim_id"], "text": claim["claim_text"], "evidence_ids": [eid]}]}
        with patch("service.deep_research_v2.science_roles.json_call", new_callable=AsyncMock, return_value=response):
            await revise_science(agent(), state)
        self.assertFalse(state["manual_review_request"]["applied"])
        self.assertEqual(state["manual_review_request"]["unchanged_requested_claim_ids"], [claim["claim_id"]])

    async def test_recheck_route_saves_archive_under_lease_before_running(self):
        full = BoundedRecheckTests().completed()
        full["query"] = full["state_json"]["query"]
        lease = Mock()
        lease.acquire = AsyncMock(return_value=lease)
        lease.release = AsyncMock()
        checkpoints = Mock(load_full_checkpoint=Mock(return_value=full), save_checkpoint=Mock(return_value="saved"))
        service = Mock(research=Mock(return_value="sse-source"))
        with patch.object(research_router_module, "authorize_research_session"), patch.object(research_router_module, "ResearchLease", return_value=lease), \
             patch.object(research_router_module, "get_checkpoint_service", return_value=checkpoints), \
             patch.object(research_router_module, "get_research_service_v2", return_value=service), \
             patch.object(research_router_module, "_response", side_effect=lambda source, _: source):
            result = await resume_research("science_test", SimpleNamespace(id="user"), Mock(), ResumeResearchRequest(additional_iterations=1))
        self.assertEqual(result, "sse-source")
        lease.acquire.assert_awaited_once()
        saved = checkpoints.save_checkpoint.call_args.args[1]
        self.assertEqual(saved["review_history"][0]["state"]["final_report"], "Original report")
        self.assertEqual(saved["phase"], "reviewing")
        self.assertTrue(service.research.call_args.kwargs["resume"])
        lease.release.assert_not_awaited()  # StreamingResponse owns the active lease.

    async def test_recheck_route_releases_lease_when_budget_is_rejected(self):
        full = BoundedRecheckTests().completed()
        lease = Mock(acquire=AsyncMock(), release=AsyncMock())
        lease.acquire.return_value = lease
        checkpoints = Mock(load_full_checkpoint=Mock(return_value=full))
        with patch.object(research_router_module, "authorize_research_session"), patch.object(research_router_module, "ResearchLease", return_value=lease), \
             patch.object(research_router_module, "get_checkpoint_service", return_value=checkpoints):
            with self.assertRaises(HTTPException):
                await resume_research("science_test", SimpleNamespace(id="user"), Mock())
        checkpoints.save_checkpoint.assert_not_called()
        lease.release.assert_awaited_once()

    async def test_scout_optional_performance_gap_does_not_force_search(self):
        state = fixture_state(1)
        add_papers(state, 1)
        state["hypotheses"] = [{"id": "hyp_1", "content": "候选模型更优", "status": "pending"}]
        with patch("service.deep_research_v2.science_retrieval.collect_scientific_evidence", new_callable=AsyncMock), \
             patch("service.deep_research_v2.science_roles.json_call", new_callable=AsyncMock, return_value={
            "hypotheses": [{"id": "hyp_1", "status": "insufficient", "evidence_ids": [], "reason": "没有可比较指标"}],
            "critical_gaps": [{"kind": "topic_coverage", "description": "缺少F1性能排名", "user_requirement_quote": "科学研究问题"}],
        }) as model:
            await scout_science(agent(), state)
            await analyze_science(agent(), state)
        model.assert_awaited_once()
        self.assertEqual(state["phase"], "analyzing")
        self.assertTrue(state["evidence_assessment"]["sufficient"])
        self.assertEqual(state["hypotheses"][0]["status"], "insufficient")
        self.assertIn("缺少F1性能排名", state["evidence_assessment"]["limitations"])

    async def test_planner_keeps_user_year_scope_and_optional_hypotheses(self):
        state = fixture_state(1)
        with patch("service.deep_research_v2.science_roles.json_call", new_callable=AsyncMock, return_value={
            "sections": [{"title": f"章节{i}"} for i in range(6)],
            "hypotheses": [{"content": "比较2020年前的基线"}, {"content": "不同方法机制的差异"}],
        }) as call:
            await plan_science(agent(), state)
        self.assertEqual(len(state["hypotheses"]), 1)
        self.assertFalse(state["hypotheses"][0]["required_for_completion"])
        self.assertEqual(state["research_constraints"]["year_range"], [2020, 2026])
        self.assertIn("用户限定的年份和主题是硬边界", call.call_args.args[1])

    async def test_critic_receives_task_scope_without_waiving_external_performance_evidence(self):
        state = fixture_state(1)
        add_papers(state, 1)
        assess_evidence(state)
        eid = state["papers"][0]["evidence_id"]
        state["claims"] = [normalize_paragraph(state, "本综述范围为2020–2026年。", [eid], "sec_1", 0),
                           normalize_paragraph(state, "该模型将F1提升20%。", [eid], "sec_1", 1)]
        state["claims"][0].update(verification_status="insufficient", reason="OLD_ANCHOR_REASON")
        rows = [review_result(state["claims"][0], "supported", "与用户限定范围一致"),
                review_result(state["claims"][1], "insufficient", "摘要未给出20%结果")]
        with patch("service.deep_research_v2.science_roles.json_call", new_callable=AsyncMock,
                   return_value={"results": rows, "critical_gaps": [], "search_tasks": []}) as call:
            await review_science(agent(), state)
        prompt = call.call_args_list[0].args[1]
        self.assertIn(state["query"], prompt)
        self.assertIn('"year_range": [2020, 2026]', prompt)
        self.assertIn('"year_distribution": {"2020": 1}', prompt)
        self.assertIn("任务范围与统计不能支持这些断言", prompt)
        self.assertIn("不得要求原文未提供的复现级材料", prompt)
        self.assertIn("没有否定", prompt)
        self.assertIn("复合段落只要一个关键子断言未获支持就判 insufficient", prompt)
        self.assertIn("表示两个及以上", prompt)
        self.assertNotIn("OLD_ANCHOR_REASON", prompt)
        self.assertNotIn('"verification_status"', prompt)
        self.assertTrue(all(c.kwargs["use_cache"] is False for c in call.call_args_list))
        self.assertEqual(state["claim_verification"]["supported"], 1)
        self.assertEqual(state["claim_verification"]["insufficient"], 1)
        self.assertEqual(state["phase"], "revising")

    async def test_critic_bypasses_model_cache_on_initial_and_retry_calls(self):
        state = fixture_state(1)
        add_papers(state, 1)
        assess_evidence(state)
        claim = normalize_paragraph(state, "作者报告定性改善。", [state["papers"][0]["evidence_id"]], "sec_1", 0)
        state["claims"] = [claim]
        fake = agent()
        fake.call_llm = AsyncMock(side_effect=["invalid-json", json.dumps({"results": [
            review_result(claim, "supported", "忠实转述已给摘要")]}),
            json.dumps({"critical_gaps": [], "search_tasks": []})])
        fake.parse_json_response.side_effect = json.loads
        await review_science(fake, state)
        self.assertEqual(fake.call_llm.await_count, 3)
        self.assertTrue(all(call.kwargs["use_cache"] is False for call in fake.call_llm.call_args_list))

    async def test_cancel_during_review_preserves_paused_checkpoint(self):
        state = fixture_state(1)
        state.update(phase="reviewing", _next_step="reviewing", final_report="Preserved research report")
        graph = DeepResearchGraph.__new__(DeepResearchGraph)
        graph.checkpoint_service = Mock()
        graph.checkpoint_service.load_full_checkpoint.return_value = None
        snapshots = []
        graph._save_checkpoint = lambda st, *args: snapshots.append(copy.deepcopy({k: v for k, v in st.items() if k != "_message_queue"})) or True
        cancelled = False
        async def review(st):
            nonlocal cancelled
            st["claims"] = [{"claim_id": "partial", "verification_status": "pending"}]
            cancelled = True
            await asyncio.sleep(10)
        graph.critic = Mock(name="critic")
        graph.critic.process = review
        with patch("service.deep_research_v2.graph.is_research_cancelled", side_effect=lambda _: cancelled), patch("service.deep_research_v2.graph.clear_cancel_flag"):
            events = [event async for event in graph._run_simplified(state)]
        self.assertEqual(events[-1]["type"], "research_cancelled")
        self.assertFalse(any(e["type"] == "error" for e in events))
        self.assertEqual(snapshots[-1]["_next_step"], "reviewing")
        self.assertEqual(snapshots[-1]["claims"][0]["claim_id"], "partial")
        self.assertEqual(snapshots[-1]["final_report"], "Preserved research report")
        self.assertEqual(snapshots[-1]["_checkpoint_status"], "paused")
        graph.checkpoint_service.update_status.assert_not_called()

    async def test_analysis_records_gap_and_authorizes_bounded_supplement(self):
        state = fixture_state(3)
        add_papers(state, 1)
        with patch("service.deep_research_v2.science_roles.json_call", new_callable=AsyncMock,
                   return_value={"critical_gaps": [], "limitations": []}):
            await analyze_science(agent(), state)
        self.assertEqual(state["phase"], "re_researching")
        self.assertFalse(state["evidence_assessment"]["sufficient"])
        self.assertTrue(state["evidence_assessment"]["missing_questions"])
        self.assertEqual(state["analysis_search_round"], 1)
        self.assertTrue(state.get("pending_search_queries"))
        self.assertEqual(state["charts"], [])

    async def test_chart_rerun_is_idempotent(self):
        state = fixture_state()
        add_papers(state, 4)
        corpus_analysis(state)
        await visualize_science(agent(), state)
        first = copy.deepcopy(state["charts"])
        await visualize_science(agent(), state)
        self.assertEqual(first, state["charts"])
        self.assertEqual(sum(first[0]["echarts_option"]["series"][0]["data"]), 4)

    async def test_scout_respects_disabled_web(self):
        state = fixture_state()
        state.update(search_web=False, search_local=False)
        with patch("service.deep_research_v2.literature_sources.collect_literature", new_callable=AsyncMock) as collect:
            await scout_science(agent(), state)
        collect.assert_not_called()
        self.assertEqual(state["papers"], [])

    async def test_critic_missing_results_stay_unverified(self):
        state = fixture_state(1)
        add_papers(state, 1)
        assess_evidence(state)
        state["claims"] = [normalize_paragraph(state, "Claim " + str(i), [state["papers"][0]["evidence_id"]], "sec_1", i) for i in range(11)]
        with patch("service.deep_research_v2.science_roles.json_call", new_callable=AsyncMock,
                   return_value={"results": [], "critical_gaps": [], "search_tasks": []}) as call:
            await review_science(agent(), state)
        self.assertEqual(call.await_count, 7)  # Three claim batches + one bounded targeted retry each + coverage.
        self.assertEqual(state["claim_verification"]["total"], 11)
        self.assertEqual(state["claim_verification"]["unverified"], 11)
        self.assertIsNone(state["quality_score"])
        self.assertEqual(state["quality_review_status"], "unconfirmed")

    async def test_industry_phase_loop_keeps_existing_analysis_search_return(self):
        state = fixture_state(1)
        state["research_profile"] = get_research_profile("industry")
        state["_next_step"] = "analyzing"
        state["phase"] = "analyzing"
        graph = DeepResearchGraph.__new__(DeepResearchGraph)
        order = []
        graph.checkpoint_service = Mock()
        graph.checkpoint_service.load_full_checkpoint.return_value = None
        snapshots = []

        def save(state, user_id=None, ui_state=None):
            snapshots.append({k: v for k, v in state.items() if not k.startswith("_message")})
            return True
        graph._save_checkpoint = save

        def make(name, function):
            async def process(st):
                order.append(name)
                function(st)
                return st
            fake = Mock()
            fake.name, fake.process = name, process
            return fake

        graph.architect = make("architect", lambda s: None)
        graph.scout = make("scout", lambda s: s.update(phase="analyzing", searched=True))
        graph.data_analyst = make("analyst", lambda s: s.update(phase="analyzing" if s.get("searched") else "re_researching", return_phase="analyzing"))
        graph.wizard = make("wizard", lambda s: None)
        graph.writer = make("writer", lambda s: s.update(final_report="Nonempty research report"))
        graph.critic = make("critic", lambda s: s.update(phase="completed"))
        with patch("service.deep_research_v2.graph.is_research_cancelled", return_value=False), patch("service.deep_research_v2.graph.clear_cancel_flag"):
            events = [event async for event in graph._run_simplified(state)]
        self.assertEqual(order, ["analyst", "scout", "analyst", "wizard", "writer", "critic"])
        self.assertTrue(any(s["_next_step"] == "re_researching" and s["return_phase"] == "analyzing" for s in snapshots))
        self.assertEqual(events[-1]["type"], "research_complete")


if __name__ == "__main__":
    unittest.main(verbosity=2)
