"""Offline dual-loop contracts. Fixtures are not research-quality measurements."""
import asyncio
import copy
import json
import unittest
from unittest.mock import AsyncMock, patch

from test_science_engine import fixture_state, add_papers, paper, agent, review_result
from service.deep_research_v2.evidence import normalize_paragraph, register_evidence
from service.deep_research_v2.science_roles import (
    analyze_science, scout_science, review_science, write_science, plan_science,
    migrate_science_policy, build_section_evidence_packets, research_scope, classify_research_gaps,
)
from service.deep_research_v2.science_retrieval import collect_scientific_evidence, ensure_retrieval_state
from service.deep_research_v2.literature_sources import query_scope, relevant

ROLE = "service.deep_research_v2.science_roles"
RETRIEVAL = "service.deep_research_v2.science_retrieval"


def reflection():
    return {"hypotheses": [], "insights": [], "critical_gaps": [], "limitations": [], "section_evidence": []}


def draft(state):
    row = normalize_paragraph(state, "作者报告使用卷积网络。", [state["papers"][0]["evidence_id"]], "sec_1", 0)
    state.update(claims=[row], science_sections=[{"id": "sec_1", "title": "方法"}])
    return row


def review_response(row, status="supported"):
    return {"results": [review_result(row, status)],
            "critical_gaps": [], "search_tasks": []}


class DualLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_reviewer_receives_four_abstracts_even_with_chunk_only_links(self):
        state = fixture_state(1)
        add_papers(state, 4)
        ids = [paper["evidence_id"] for paper in state["papers"]]
        claim = normalize_paragraph(state, "本次四篇摘要是否提供了可比的实验依据仍需逐项核验。", ids, "sec_1", 0)
        state.update(claims=[claim], science_sections=[{"id": "sec_1", "title": "实验口径"}])
        captured = []

        async def response(_agent, prompt, **kwargs):
            if "逐条审核" in prompt:
                captured.append(prompt)
                return {"results": [review_result(claim, "unverified", "fixture: cannot complete semantic review")]}
            return {"critical_gaps": [], "search_tasks": []}

        with patch(ROLE + ".json_call", side_effect=response):
            await review_science(agent(), state)
        self.assertEqual(len(captured), 1)
        self.assertIn("text 是本次已经提供的原始摘要或正文片段", captured[0])
        self.assertIn("缺少 quote/locator 不等于缺少 text", captured[0])
        self.assertIn("text 存在也不能自动通过", captured[0])
        payload = json.loads(captured[0].rsplit("\n证据：", 1)[1])
        self.assertEqual({row["evidence_id"] for row in payload}, set(ids))
        self.assertTrue(all(row["evidence_level"] == "abstract" and row["text"] for row in payload))
        # Prompt clarification never coerces an unresolved response to supported.
        self.assertEqual(state["claims"][0]["verification_status"], "unverified")
        self.assertEqual(state["review_verdict"], "unconfirmed")

    async def test_planner_outputs_remain_unverified_tasks_not_evidence(self):
        state = fixture_state(1)
        preconception = "尚无研究可比，所有研究均不一致。"
        sections = [{"title": f"Topic {i}", "description": preconception,
                     "expected_output": "检索后给出有边界的回答", "search_queries": ["biomedical retrieval"],
                     "information_role": "evidence", "verification_status": "supported"} for i in range(4)]
        with patch(ROLE + ".json_call", new_callable=AsyncMock, return_value={"sections": sections}) as model:
            await plan_science(agent(), state)
        prompt = model.await_args.args[1]
        self.assertIn("所有章节（包括结论与建议）均只提出待验证的问题", prompt)
        self.assertNotIn("最后一节必须给出有依据的综合结论", prompt)
        self.assertIn("不要预设", prompt)
        self.assertFalse(state["evidence_ledger"])
        self.assertFalse(state["claims"])
        for row in state["outline"] + state["research_tasks"]:
            self.assertEqual(row["information_role"], "planning_only")
            self.assertEqual(row["verification_status"], "unverified")
        # Metadata and consumer prompts establish the boundary; no fragile
        # regex pretends to validate or erase arbitrary scientific statements.
        self.assertEqual(state["outline"][0]["description"], preconception)

    async def test_fallback_plan_keeps_conclusion_as_pending_question(self):
        state = fixture_state(1)
        with patch(ROLE + ".json_call", new_callable=AsyncMock, side_effect=ValueError("offline planner failure")):
            await plan_science(agent(), state)
        self.assertTrue(all(s["description"].endswith("？") for s in state["outline"]))
        self.assertEqual(state["outline"][-1]["verification_status"], "unverified")
        self.assertFalse(state["evidence_ledger"])

    async def test_analysis_cannot_inherit_fact_from_legacy_outline(self):
        state = fixture_state(1)
        add_papers(state, 1)
        state["outline"] = [{"id": "sec_1", "title": "比较", "description": "所有领域文献均不可比。"}]
        with patch(ROLE + ".json_call", new_callable=AsyncMock, return_value=reflection()) as model:
            await analyze_science(agent(), state)
        prompt = model.await_args.args[1]
        self.assertIn("planning_only / unverified", prompt)
        self.assertIn("不能继承其结论", prompt)
        self.assertIn("不等于“整个领域不存在”", prompt)
        self.assertIn('"search_queries"', prompt)
        self.assertIn("不复制诊断段落", prompt)

    async def test_writer_does_not_treat_legacy_plan_as_fact(self):
        state = fixture_state(1)
        add_papers(state, 1)
        state["outline"] = [{"id": f"sec_{i}", "title": f"Topic {i}",
                             "description": "所有领域文献均不可比。"} for i in range(4)]
        eid = state["papers"][0]["evidence_id"]
        with patch(ROLE + ".json_call", new_callable=AsyncMock, return_value={"paragraphs": [
            {"text": "作者报告使用卷积网络。", "evidence_ids": [eid]},
            {"text": "本次文献不能支持全领域否定性结论。", "evidence_ids": [eid]},
        ]}) as model:
            await write_science(agent(), state)
        self.assertEqual(model.await_count, 4)
        for call in model.await_args_list:
            prompt = call.args[1]
            self.assertIn("planning_only / unverified", prompt)
            self.assertIn("不能沿用为答案", prompt)
            self.assertIn("不等于“整个领域不存在”", prompt)

    async def test_scout_local_search_preserves_server_authorized_knowledge_base_id(self):
        for phase in ("researching", "re_researching"):
            with self.subTest(phase=phase):
                state = fixture_state(1)
                task = {"task_id": "task_owned_kb", "query": "授权知识库中的研究片段"}
                state.update(phase=phase, search_web=False, search_local=True,
                             kb_name="同名知识库", knowledge_base_id="server-authorized-kb-id",
                             _user_id="authenticated-owner-id", research_tasks=[task],
                             active_retrieval_tasks=[task])
                scout = agent()
                scout._execute_local_search = AsyncMock(return_value=[])

                await scout_science(scout, state)

                scout._execute_local_search.assert_awaited_once_with(
                    task["query"], kb_name="同名知识库", user_id="authenticated-owner-id",
                    knowledge_base_id="server-authorized-kb-id")

    async def test_analysis_service_failure_is_not_sufficiency(self):
        state = fixture_state(1)
        add_papers(state, 2)
        with patch(ROLE + ".json_call", new_callable=AsyncMock, side_effect=ValueError("fixture unavailable")):
            await analyze_science(agent(), state)
        self.assertFalse(state["evidence_assessment"]["sufficient"])
        self.assertEqual(state["phase"], "completed")
        self.assertEqual(state["analysis_decision"], "stop")
        self.assertEqual(state["review_verdict"], "unconfirmed")
        self.assertEqual(state["stop_reason"], "analysis_unavailable")
        self.assertFalse(state["claims"])

    async def test_analysis_missing_coverage_decision_does_not_pass_on_count(self):
        state = fixture_state(1)
        add_papers(state, 2)
        with patch(ROLE + ".json_call", new_callable=AsyncMock, return_value={"hypotheses": []}):
            await analyze_science(agent(), state)
        self.assertEqual(state["analysis_semantic_status"], "unconfirmed")
        self.assertFalse(state["evidence_assessment"]["sufficient"])
        self.assertEqual(state["phase"], "completed")

    async def test_partial_corpus_retrieves_before_writer_without_spending_review_budget(self):
        state = fixture_state(3)
        add_papers(state, 1)
        with patch(ROLE + ".json_call", new_callable=AsyncMock, return_value=reflection()):
            await analyze_science(agent(), state)
        self.assertEqual(state["phase"], "re_researching")
        self.assertEqual(state["supplementary_origin"], "analysis")
        self.assertEqual(state["analysis_search_round"], 1)
        self.assertEqual(state["iteration"], 0)
        self.assertTrue(state["pending_search_queries"])

    async def test_no_readable_evidence_and_no_retrieval_stops_without_review_pass(self):
        state = fixture_state(1)
        state.update(search_web=False, search_local=False)
        await analyze_science(agent(), state)
        self.assertEqual(state["phase"], "completed")
        self.assertEqual(state["outcome"], "insufficient_evidence")
        self.assertEqual(state["review_verdict"], "not_reviewed")
        self.assertTrue(state["final_report"])

    async def test_analysis_budget_is_bounded_and_readable_partial_report_is_explicitly_degraded(self):
        state = fixture_state(3)
        add_papers(state, 1)
        state["analysis_search_round"] = 2
        with patch(ROLE + ".json_call", new_callable=AsyncMock, return_value=reflection()):
            await analyze_science(agent(), state)
        self.assertEqual(state["phase"], "analyzing")
        self.assertTrue(state["evidence_assessment"]["degraded"])
        self.assertEqual(state["analysis_search_round"], 2)
        self.assertEqual(state["analysis_stop_reason"], "analysis_budget_exhausted")

    async def test_scout_only_acquires_and_analysis_owns_semantic_check(self):
        state = fixture_state(1)
        add_papers(state, 1)
        with patch(RETRIEVAL + ".collect_scientific_evidence", new_callable=AsyncMock), \
             patch(ROLE + ".json_call", new_callable=AsyncMock, return_value=reflection()) as model:
            await scout_science(agent(), state)
            model.assert_not_awaited()
            await analyze_science(agent(), state)
            model.assert_awaited_once()

    async def test_optional_hypothesis_does_not_authorize_supplement(self):
        state = fixture_state(1)
        add_papers(state, 1)
        state["hypotheses"] = [{"id": "hyp_1", "content": "尚待验证的假设"}]
        result = reflection()
        result["hypotheses"] = [{"id": "hyp_1", "status": "insufficient", "evidence_ids": [], "reason": "没有可比实验"}]
        with patch(ROLE + ".json_call", new_callable=AsyncMock, return_value=result):
            await analyze_science(agent(), state)
        self.assertEqual(state["phase"], "analyzing")
        self.assertEqual(state["analysis_search_round"], 0)

    async def test_reviewer_can_reject_analysis_candidate_gap(self):
        state = fixture_state(1)
        add_papers(state, 1)
        row = draft(state)
        state["evidence_assessment"] = {"topic_gaps": ["候选：缺少机制"], "topic_queries": ["candidate query"]}
        with patch(ROLE + ".json_call", new_callable=AsyncMock, return_value=review_response(row)):
            await review_science(agent(), state)
        self.assertEqual(state["review_verdict"], "pass")
        self.assertFalse(state["review_search_tasks"])
        self.assertFalse(state["evidence_assessment"]["topic_gaps"])
        self.assertTrue(state["review_candidate_gaps"]["gaps"])

    async def test_contradiction_returns_to_analysis_before_revision(self):
        state = fixture_state(1)
        add_papers(state, 1)
        row = draft(state)
        with patch(ROLE + ".json_call", new_callable=AsyncMock, return_value=review_response(row, "contradicted")):
            await review_science(agent(), state)
        self.assertEqual(state["phase"], "analyzing")
        self.assertEqual(state["analysis_continuation"], "revising")
        self.assertEqual(state["iteration"], 1)

    async def test_review_service_failure_retries_without_rewriting_and_then_stops_unconfirmed(self):
        state = fixture_state(1)
        add_papers(state, 1)
        row = draft(state)
        original = row["claim_text"]
        async def unavailable(_agent, prompt, **kwargs):
            if "逐条审核" in prompt:
                raise RuntimeError("fixture unavailable")
            return {"critical_gaps": [], "search_tasks": []}
        with patch(ROLE + ".json_call", side_effect=unavailable):
            await review_science(agent(), state)
            self.assertEqual(state["phase"], "review_retry")
            await review_science(agent(), state)
        self.assertEqual(state["phase"], "completed")
        self.assertEqual(state["outcome"], "completed_with_warnings")
        self.assertEqual(state["review_verdict"], "unconfirmed")
        self.assertEqual(state["claims"][0]["claim_text"], original)

    async def test_exhausted_review_budget_is_not_quality_pass(self):
        state = fixture_state(1)
        add_papers(state, 1)
        row = draft(state)
        state["iteration"] = state["max_iterations"]
        with patch(ROLE + ".json_call", new_callable=AsyncMock, return_value=review_response(row, "insufficient")):
            await review_science(agent(), state)
        self.assertEqual(state["phase"], "completed")
        self.assertEqual(state["outcome"], "completed_with_warnings")
        self.assertEqual(state["review_verdict"], "needs_revision")
        self.assertEqual(state["stop_reason"], "review_budget_exhausted")

    async def test_writer_failure_drains_siblings_without_partial_state_commit(self):
        state = fixture_state(1)
        add_papers(state, 3)
        state.update(phase="writing", outline=[{"id": f"sec_{i}", "title": f"Topic {i}", "description": "neural mechanism"} for i in range(4)])
        cancelled = []
        async def chapter(_agent, prompt, **kwargs):
            if '"title": "Topic 0"' in prompt:
                await asyncio.sleep(0)
                raise ValueError("fixture chapter failure")
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise
        with patch(ROLE + ".json_call", side_effect=chapter):
            with self.assertRaises(ValueError):
                await write_science(agent(), state)
        self.assertTrue(cancelled)
        self.assertEqual(state["draft_sections"], {})
        self.assertEqual(state["claims"], [])
        self.assertFalse([t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()])

    async def test_planner_queries_and_section_links_reach_real_collector(self):
        state = fixture_state(1)
        state["research_profile"]["science_retrieval"]["max_batch_queries"] = 4
        sections = [{"title": f"Section {i}", "description": f"Question {i}", "search_queries": [f"neural mechanism {i}"]} for i in range(4)]
        with patch(ROLE + ".json_call", new_callable=AsyncMock, return_value={"sections": sections}):
            await plan_science(agent(), state)
        captured = []
        async def collect(*args, **kwargs):
            captured.append(kwargs["search_terms"])
            return [paper(1)]
        with patch(RETRIEVAL + ".collect_literature", side_effect=collect), \
             patch(RETRIEVAL + "._propose", new_callable=AsyncMock, return_value=[]):
            await collect_scientific_evidence(agent(), state)
        self.assertEqual(captured, [[f"neural mechanism {i}"] for i in range(4)])
        eid = state["papers"][0]["evidence_id"]
        self.assertEqual(set(state["retrieval_evidence_links"][eid]["section_ids"]), {f"sec_{i}" for i in range(1,5)})


class WorkflowContractTests(unittest.TestCase):
    def test_analysis_search_queries_do_not_reuse_diagnostic_reason(self):
        query = "比较 biomedical retrieval 的 Recall@20。"
        reason = "缺少可比实验，ev_internal123 和 claim_private456 均没有支持。"
        gap = {"kind": "required_comparison", "description": reason,
               "user_requirement_quote": "Recall@20",
               "search_queries": ["biomedical retrieval Recall@20 dense hybrid", "biomedical retrieval evaluation"]}
        critical, limitations, searches = classify_research_gaps({"critical_gaps": [gap]}, query)
        self.assertEqual(critical, [reason])
        self.assertFalse(limitations)
        self.assertEqual(searches, gap["search_queries"])
        self.assertNotIn("ev_internal123", " ".join(searches))
        self.assertNotIn("claim_private456", " ".join(searches))

    def test_legacy_gap_missing_search_queries_falls_back_to_user_question(self):
        query = "比较 biomedical retrieval 的 Recall@20。"
        gap = {"kind": "required_comparison", "description": "ev_internal123缺少可比实验。",
               "user_requirement_quote": "Recall@20"}
        for proposed in (None, "long diagnostic reason", [None, 123, ""]):
            with self.subTest(proposed=proposed):
                gap["search_queries"] = proposed
                _, _, searches = classify_research_gaps({"critical_gaps": [gap]}, query)
                self.assertEqual(searches, [query])

    def test_optional_gap_cannot_inject_search_queries(self):
        query = "综述 biomedical retrieval 方法。"
        gap = {"kind": "required_comparison", "description": "缺少Recall@20排名。",
               "user_requirement_quote": "biomedical retrieval", "search_queries": ["unrequested metrics"]}
        critical, limitations, searches = classify_research_gaps({"critical_gaps": [gap]}, query)
        self.assertFalse(critical)
        self.assertTrue(limitations)
        self.assertFalse(searches)

    def test_explicit_retrieval_latency_and_percentage_metrics_require_comparison(self):
        for metric in ("Recall@20", "recall @ K", "Precision@10", "precision @ k", "MRR", "nDCG@10",
                       "nDCG", "p50", "P95", "p99.9", "latency", "latencies", "延迟", "时延", "百分点差",
                       "percentage point difference", "percentage points"):
            with self.subTest(metric=metric):
                self.assertTrue(research_scope(f"比较两种方法的{metric}，说明评测口径。")
                                ["requires_quantitative_comparison"])
        self.assertTrue(research_scope("Compare Recall@20 and p50 latency")
                        ["requires_quantitative_comparison"])

    def test_explicit_recall_and_latency_gap_stays_required(self):
        query = "比较 Recall@20、p50 延迟，并计算百分点差。"
        description = "缺少相同评测条件下的 Recall@20 与 p50 延迟"
        critical, limitations, searches = classify_research_gaps({"critical_gaps": [{
            "kind": "required_comparison", "description": description,
            "user_requirement_quote": "Recall@20、p50 延迟"}]}, query)
        self.assertEqual(critical, [description])
        self.assertFalse(limitations)
        self.assertEqual(len(searches), 1)

    def test_plain_method_review_does_not_gain_generated_metric_requirements(self):
        query = "综述检索增强生成方法的架构、适用场景和局限。"
        for ordinary in (query, "Review recall mechanisms in human memory", "Survey precision agriculture methods"):
            with self.subTest(query=ordinary):
                self.assertFalse(research_scope(ordinary)["requires_quantitative_comparison"])
        gaps = [{"kind": kind, "description": f"缺少{metric}证据", "user_requirement_quote": "检索增强生成方法"}
                for kind in ("required_comparison", "topic_coverage")
                for metric in ("Recall@20", "Precision@K", "MRR", "nDCG", "p50 延迟", "百分点差")]
        critical, limitations, searches = classify_research_gaps({"critical_gaps": gaps}, query)
        self.assertFalse(critical)
        self.assertFalse(searches)
        self.assertEqual(len(limitations), 6)

    def test_migration_preserves_spent_budgets_and_analysis_continuation(self):
        state = fixture_state(1)
        state["research_profile"].update(supplementary_policy="review_only", max_analysis_search_rounds=0)
        state.update(phase="re_researching", _next_step="re_researching", supplementary_origin="analysis",
                     analysis_search_round=2, iteration=2, pending_search_queries=["pending"],
                     science_retrieval={"requests_used": 12, "elapsed_seconds": 40})
        before = copy.deepcopy(state["science_retrieval"])
        migrate_science_policy(state)
        self.assertEqual(state["phase"], "re_researching")
        self.assertEqual(state["analysis_search_round"], 2)
        self.assertEqual(state["iteration"], 2)
        self.assertEqual(state["science_retrieval"], before)
        self.assertEqual(state["pending_search_queries"], ["pending"])

    def test_chinese_chapter_packets_use_relevance_not_round_robin(self):
        state = fixture_state(1)
        segmentation = register_evidence(state, paper(1, title="图像分割的边界学习", abstract="图像分割采用边界约束。" * 20))
        detection = register_evidence(state, paper(2, title="目标检测的定位方法", abstract="目标检测预测边界框并定位物体。" * 20))
        state["outline"] = [{"id": "seg", "title": "图像分割", "description": "边界学习"},
                            {"id": "det", "title": "目标检测", "description": "定位物体"}]
        packets = build_section_evidence_packets(state)
        self.assertEqual(packets["seg"]["evidence_ids"], [segmentation["evidence_id"]])
        self.assertEqual(packets["det"]["evidence_ids"], [detection["evidence_id"]])

    def test_remote_sensing_does_not_implicitly_exclude_radar(self):
        scope = query_scope("综述2020-2026年遥感变化检测")
        self.assertFalse(scope["optical_change_detection"])
        self.assertTrue(relevant("SAR remote sensing change detection", "Radar imagery comparison", scope))
        explicit = query_scope("综述2020-2026年光学遥感变化检测，排除SAR")
        self.assertFalse(relevant("SAR and optical remote sensing change detection", "Optical data", explicit))

    def test_legacy_scope_migration_corrects_only_implicit_modality_not_dates_or_budget(self):
        state = fixture_state(1)
        state["query"] = "综述遥感变化检测"
        state["science_retrieval"] = {"schema_version": 1, "original_query": state["query"],
            "scope": {"start_year": 2020, "end_year": 2025, "until": "2025-08-01", "optical_change_detection": True,
                      "searches": ["optical remote sensing change detection"]},
            "requests_used": 9, "documents_used": 500, "elapsed_seconds": 40}
        migrated = ensure_retrieval_state(state)
        self.assertFalse(migrated["scope"]["optical_change_detection"])
        self.assertEqual(migrated["scope"]["until"], "2025-08-01")
        self.assertEqual(migrated["scope"]["start_year"], 2020)
        self.assertEqual(migrated["requests_used"], 9)
        self.assertEqual(migrated["documents_used"], 500)
        self.assertEqual(migrated["elapsed_seconds"], 40)


if __name__ == "__main__":
    unittest.main()
