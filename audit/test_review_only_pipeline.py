"""Offline regressions for Review-owned retrieval and scientific phase routing.

Network and model outputs are fixtures. These tests validate decisions and state
transitions, not literature quality or live provider availability.
"""
import asyncio
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_science_engine import fixture_state, paper, add_papers, agent
from service.deep_research_v2.evidence import normalize_paragraph, register_evidence
from service.deep_research_v2.graph import DeepResearchGraph
from service.deep_research_v2.science_roles import (analyze_science, assess_evidence, review_science, scout_science,
                                                  revise_science, migrate_science_policy, authorize_review_search)


ROLE = "service.deep_research_v2.science_roles"
GRAPH = "service.deep_research_v2.graph"


def claim(state, text="作者提出孪生卷积网络。", index=0):
    row = normalize_paragraph(state, text, [state["papers"][0]["evidence_id"]], "sec_1", index)
    state["claims"].append(row)
    state["science_sections"] = [{"id": "sec_1", "title": "方法比较"}]
    return row


def response(row, status="supported", **extra):
    return {"results": [{"claim_id": row["claim_id"], "status": status,
                         "reason": "摘要直接支持方法描述" if status == "supported" else "摘要没有所声称的对比实验数值"}],
            "critical_gaps": [], "search_tasks": [], **extra}


class ReviewOwnedRetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def test_analyze_records_source_gap_without_authorizing_search(self):
        state = fixture_state(3)
        add_papers(state, 1)
        state.update(phase="analyzing", iteration=1, analysis_search_round=1)
        before = state["iteration"]
        await analyze_science(agent(), state)
        self.assertEqual(state["phase"], "analyzing")
        self.assertFalse(state["evidence_assessment"]["sufficient"])
        self.assertTrue(state["evidence_assessment"]["missing_questions"])
        self.assertEqual(state["iteration"], before)
        self.assertEqual(state["analysis_search_round"], 1)
        self.assertFalse(state.get("pending_search_queries"))
        self.assertNotEqual(state.get("supplementary_origin"), "analysis")

    async def test_no_evidence_reaches_review_preflight_without_exception(self):
        state = fixture_state(1)
        await analyze_science(agent(), state)
        self.assertEqual(state["phase"], "reviewing")
        self.assertTrue(state["review_preflight"])
        self.assertFalse(state.get("pending_search_queries"))
        self.assertFalse(state["claims"])

    async def test_metadata_only_cannot_reach_writer_as_readable_evidence(self):
        state = fixture_state(1)
        state["papers"] = [register_evidence(state, paper(1, abstract="", content="Title " * 50,
                                                       evidence_level="metadata"))]
        await analyze_science(agent(), state)
        self.assertEqual(state["phase"], "reviewing")
        self.assertTrue(state["review_preflight"])
        self.assertEqual(state["evidence_assessment"]["required_evidence"]["content_bearing_sources"], 0)

    async def test_scout_reassesses_hypotheses_even_when_source_count_is_short(self):
        state = fixture_state(3)
        add_papers(state, 1)
        state["hypotheses"] = [{"id": "hyp_1", "content": "孪生卷积网络被使用", "status": "pending"}]
        eid = state["papers"][0]["evidence_id"]
        with patch("service.deep_research_v2.science_retrieval.collect_scientific_evidence", new_callable=AsyncMock), \
             patch(ROLE + ".json_call", new_callable=AsyncMock, return_value={
            "hypotheses": [{"id": "hyp_1", "status": "supported", "evidence_ids": [eid], "reason": "直接文字"}],
            "critical_gaps": [], "limitations": [],
        }) as model:
            await scout_science(agent(), state)
            await analyze_science(agent(), state)
        model.assert_awaited_once()
        self.assertEqual(state["hypotheses"][0]["status"], "supported")
        self.assertFalse(state["evidence_assessment"]["sufficient"])
        self.assertEqual(state["phase"], "analyzing")

    async def test_review_refreshes_stale_source_assessment_after_supplement(self):
        state = fixture_state(2)
        add_papers(state, 1)
        self.assertFalse(assess_evidence(state)["sufficient"])
        add_papers(state, 3)
        row = claim(state)
        with patch(ROLE + ".json_call", new_callable=AsyncMock, return_value=response(row)):
            await review_science(agent(), state)
        self.assertTrue(state["evidence_assessment"]["sufficient"])
        self.assertEqual(state["phase"], "completed")
        self.assertEqual(state["claim_verification"]["supported"], 1)
        self.assertFalse(state.get("pending_search_queries"))

    async def test_review_targets_a_missing_claim_in_an_otherwise_sufficient_corpus(self):
        state = fixture_state(1)
        state["query"] = "比较2020-2026年光学遥感变化检测的F1性能。"
        add_papers(state, 2)
        row = claim(state, "LEVIR数据集上方法A的F1为90%。")
        focused = "optical remote sensing change detection LEVIR F1 method A experiment"
        task = {"kind": "claim_evidence", "claim_id": row["claim_id"], "section_id": "sec_1",
                "reason": "用户要求比较F1，需要原始实验数据", "query": focused, "action": "search",
                "user_requirement_quote": "F1性能"}
        with patch(ROLE + ".json_call", new_callable=AsyncMock,
                   return_value=response(row, "insufficient", search_tasks=[task])):
            await review_science(agent(), state)
        self.assertEqual(state["phase"], "re_researching")
        self.assertEqual(state["supplementary_origin"], "critic")
        self.assertTrue(any(focused in query for query in state["pending_search_queries"]))
        self.assertEqual(state["claim_verification"]["insufficient"], 1)

    async def test_unknown_claim_cannot_authorize_a_search(self):
        state = fixture_state(1)
        add_papers(state, 1)
        row = claim(state, "该方法的F1提高20%。")
        with patch(ROLE + ".json_call", new_callable=AsyncMock, return_value=response(row, "insufficient",
            search_tasks=[{"kind": "claim_evidence", "claim_id": "invented_claim", "action": "search",
                           "query": "unrelated biomedical data", "reason": "invented"}])):
            await review_science(agent(), state)
        self.assertEqual(state["phase"], "revising")
        self.assertFalse(state.get("pending_search_queries"))

    async def test_review_can_choose_revision_instead_of_searching_for_an_optional_number(self):
        state = fixture_state(1)
        add_papers(state, 1)
        row = claim(state, "该方法的F1提高20%。")
        with patch(ROLE + ".json_call", new_callable=AsyncMock, return_value=response(row, "insufficient",
            search_tasks=[{"kind": "claim_evidence", "claim_id": row["claim_id"], "action": "revise",
                           "reason": "原任务只要求方法综述，应删除无依据的20%数字"}])):
            await review_science(agent(), state)
        self.assertEqual(state["phase"], "revising")
        self.assertFalse(state.get("pending_search_queries"))

    async def test_all_supported_claims_do_not_hide_an_omitted_user_topic(self):
        state = fixture_state(1)
        state["query"] = "综述2020-2026年光学遥感变化检测的卷积与Transformer方法。"
        add_papers(state, 1)
        row = claim(state)
        gap = {"kind": "topic_coverage", "description": "报告没有覆盖Transformer方法机制",
               "user_requirement_quote": "Transformer方法", "section_id": "sec_1"}
        with patch(ROLE + ".json_call", new_callable=AsyncMock,
                   return_value=response(row, critical_gaps=[gap])):
            await review_science(agent(), state)
        self.assertEqual(state["claim_verification"]["supported"], 1)
        self.assertEqual(state["phase"], "re_researching")
        self.assertFalse(state["evidence_assessment"]["sufficient"])
        self.assertTrue(any("Transformer" in query for query in state["pending_search_queries"]))

    async def test_explicit_review_search_task_cannot_be_ignored_as_a_pass(self):
        state = fixture_state(1)
        state["query"] = "综述2020-2026年光学遥感变化检测的卷积与Transformer方法。"
        add_papers(state, 1)
        row = claim(state)
        task = {"kind": "topic_coverage", "action": "search", "reason": "缺少Transformer方法机制材料",
                "user_requirement_quote": "Transformer方法", "query": "optical change detection transformer mechanism"}
        with patch(ROLE + ".json_call", new_callable=AsyncMock,
                   return_value=response(row, search_tasks=[task])):
            await review_science(agent(), state)
        self.assertEqual(state["phase"], "re_researching")
        self.assertTrue(state["pending_search_queries"])

    async def test_incomplete_task_coverage_response_never_passes(self):
        state = fixture_state(1)
        add_papers(state, 1)
        row = claim(state)
        missing_decision = {"results": response(row)["results"]}
        with patch(ROLE + ".json_call", new_callable=AsyncMock, return_value=missing_decision):
            await review_science(agent(), state)
        self.assertEqual(state["claim_verification"]["supported"], 1)
        self.assertEqual(state["task_coverage_review"]["status"], "unconfirmed")
        self.assertEqual(state["quality_review_status"], "unconfirmed")
        self.assertIsNone(state["quality_score"])
        self.assertNotEqual(state["phase"], "completed")

    async def test_same_review_query_is_not_authorized_again_after_a_failed_search(self):
        state = fixture_state(2)
        add_papers(state, 1)
        row = claim(state)
        with patch(ROLE + ".json_call", new_callable=AsyncMock, return_value=response(row)):
            await review_science(agent(), state)
            self.assertEqual(state["phase"], "re_researching")
            first_round = state["review_search_round"]
            state.update(phase="reviewing", pending_search_queries=[])
            await review_science(agent(), state)
        self.assertEqual(state["phase"], "revising")
        self.assertEqual(state["review_search_round"], first_round)
        self.assertFalse(state["pending_search_queries"])

    async def test_review_does_not_repeat_a_query_already_visited_by_recursive_scout(self):
        state = fixture_state(1)
        state["query"] = "综述2020-2026年光学遥感变化检测的卷积与Transformer方法。"
        add_papers(state, 1)
        row = claim(state)
        state["science_retrieval"] = {"visited": ["optical change detection transformer mechanism"],
                                      "requests_used": 7, "documents_used": 680, "recursive_queries_used": 2}
        state["review_search_round"] = 1
        task = {"kind": "topic_coverage", "action": "search", "reason": "缺少Transformer方法机制材料",
                "user_requirement_quote": "Transformer方法",
                "query": state["query"] + " ; Optical change-detection Transformer mechanism"}
        with patch(ROLE + ".json_call", new_callable=AsyncMock,
                   return_value=response(row, search_tasks=[task])):
            await review_science(agent(), state)
        self.assertEqual(state["phase"], "revising")
        self.assertEqual(state["review_search_round"], 1)
        self.assertFalse(state.get("pending_search_queries"))
        self.assertFalse(state.get("review_search_history"))
        self.assertTrue(state["review_revision_requests"])

    async def test_missing_topic_can_be_added_without_rewriting_supported_claims(self):
        state = fixture_state(1)
        add_papers(state, 2)
        existing = claim(state)
        existing["verification_status"] = "supported"
        before = copy.deepcopy(existing)
        state["review_revision_requests"] = ["补充Transformer机制与局限"]
        addition = {"section_id": "sec_1", "text": "论文摘要描述了注意力机制的应用范围。",
                    "evidence_ids": [state["papers"][1]["evidence_id"]]}
        with patch(ROLE + ".json_call", new_callable=AsyncMock,
                   return_value={"revisions": [], "additions": [addition]}) as model:
            await revise_science(agent(), state)
        model.assert_awaited_once()
        self.assertEqual(state["claims"][0], before)
        self.assertEqual(len(state["claims"]), 2)
        self.assertEqual(state["claims"][1]["verification_status"], "pending")
        self.assertEqual(state["claims"][1]["evidence_ids"], addition["evidence_ids"])
        self.assertEqual(state["phase"], "reviewing")

    async def test_revision_rejects_unknown_section_or_unregistered_evidence(self):
        state = fixture_state(1)
        add_papers(state, 1)
        existing = claim(state)
        existing["verification_status"] = "supported"
        state["review_revision_requests"] = ["补充缺失主题"]
        invalid = [{"section_id": "invented_section", "text": "无效章节", "evidence_ids": [state["papers"][0]["evidence_id"]]},
                   {"section_id": "sec_1", "text": "凭空引用", "evidence_ids": ["invented_evidence"]},
                   {"section_id": "sec_1", "text": existing["claim_text"], "evidence_ids": existing["evidence_ids"]}]
        with patch(ROLE + ".json_call", new_callable=AsyncMock, return_value={"revisions": [], "additions": invalid}):
            await revise_science(agent(), state)
        self.assertEqual(len(state["claims"]), 1)
        self.assertEqual(state["phase"], "reviewing")

    async def test_preflight_authorizes_rescue_without_fabricating_claims(self):
        state = fixture_state(1)
        state.update(phase="reviewing", review_preflight=True)
        with patch(ROLE + ".json_call", new_callable=AsyncMock, return_value={"search_tasks": []}):
            await review_science(agent(), state)
        self.assertEqual(state["phase"], "re_researching")
        self.assertEqual(state["supplementary_origin"], "critic")
        self.assertTrue(state["pending_search_queries"])
        self.assertFalse(state["claims"])
        self.assertIsNone(state["quality_score"])
        self.assertNotEqual(state["quality_review_status"], "confirmed")

    async def test_preflight_disabled_search_ends_with_honest_evidence_failure(self):
        state = fixture_state(1)
        state.update(phase="reviewing", review_preflight=True, search_web=False, search_local=False)
        await review_science(agent(), state)
        self.assertEqual(state["phase"], "completed")
        self.assertIsNone(state["quality_score"])
        self.assertNotEqual(state["quality_review_status"], "confirmed")
        self.assertFalse(state["claims"])
        self.assertTrue(state["final_report"].strip())
        self.assertIn("证据", state["final_report"])
        self.assertFalse(state.get("pending_search_queries"))

    async def test_exhausted_preflight_budget_is_not_a_successful_review(self):
        state = fixture_state(1)
        state.update(phase="reviewing", review_preflight=True, iteration=2, max_iterations=2)
        await review_science(agent(), state)
        self.assertEqual(state["phase"], "completed")
        self.assertEqual(state["iteration"], 2)
        self.assertIsNone(state["quality_score"])
        self.assertNotEqual(state["quality_review_status"], "confirmed")
        self.assertTrue(state["final_report"].strip())
        self.assertFalse(state.get("pending_search_queries"))

    async def test_web_budget_exhaustion_does_not_consume_a_useless_review_round(self):
        for field, consumed in (("requests_used", 48), ("documents_used", 2400), ("elapsed_seconds", 600)):
            with self.subTest(field=field):
                state = fixture_state(1)
                state.update(phase="reviewing", review_preflight=True, search_web=True, search_local=False,
                             science_retrieval={field: consumed})
                await review_science(agent(), state)
                self.assertEqual(state["phase"], "completed")
                self.assertEqual(state["iteration"], 0)
                self.assertIsNone(state["quality_score"])
                self.assertFalse(state.get("pending_search_queries"))

    async def test_exhausted_web_budget_still_allows_enabled_local_evidence_rescue(self):
        state = fixture_state(1)
        state.update(phase="reviewing", review_preflight=True, search_web=True, search_local=True,
                     science_retrieval={"requests_used": 48, "documents_used": 2400, "elapsed_seconds": 600})
        await review_science(agent(), state)
        self.assertEqual(state["phase"], "re_researching")
        self.assertEqual(state["supplementary_origin"], "critic")
        self.assertEqual(state["iteration"], 1)
        self.assertTrue(state["pending_search_queries"])

    async def test_budget_exhaustion_preserves_unsupported_claim_status(self):
        state = fixture_state(1)
        add_papers(state, 1)
        state.update(iteration=2, max_iterations=2)
        row = claim(state, "该方法F1为90%。")
        with patch(ROLE + ".json_call", new_callable=AsyncMock, return_value=response(row, "insufficient")):
            await review_science(agent(), state)
        self.assertEqual(state["phase"], "completed")
        self.assertEqual(state["iteration"], 2)
        self.assertEqual(state["claims"][0]["verification_status"], "insufficient")
        self.assertGreater(state["unresolved_issues"], 0)
        self.assertFalse(state.get("pending_search_queries"))


class CheckpointMigrationTests(unittest.TestCase):
    def test_legacy_search_usage_is_initialized_before_authorization_charges_a_round(self):
        state = fixture_state(1)
        add_papers(state, 1)
        state.update(iteration=3, max_iterations=5, science_retrieval={})
        task = {"kind": "topic_coverage", "reason": "缺失明确要求的主题",
                "query": "optical remote sensing evidence", "query_key": "optical remote sensing evidence"}
        authorized = authorize_review_search(agent(), state, [task])
        self.assertFalse(authorized)
        self.assertEqual((state["iteration"], state["max_iterations"]), (3, 5))
        self.assertEqual(state["science_retrieval"]["documents_used"], 2720)
        self.assertEqual(state["science_retrieval"]["requests_used"], 28)
        self.assertEqual(state["science_retrieval"]["legacy_usage_estimate"]["batches"], 4)
        self.assertFalse(state.get("review_search_round"))
        self.assertFalse(state.get("review_search_history"))
        self.assertFalse(state.get("pending_search_queries"))

    def test_legacy_analysis_search_returns_to_review_without_budget_reset(self):
        state = fixture_state(2)
        state.update(phase="re_researching", _next_step="re_researching", supplementary_origin="analysis",
                     pending_search_queries=["old missing evidence"], analysis_search_round=2,
                     iteration=2, max_iterations=3, review_search_round=1,
                     science_retrieval={"recursive_queries_used": 4, "requests_used": 14,
                                        "documents_used": 420, "visited": ["already searched"]})
        prior = copy.deepcopy(state["science_retrieval"])
        migrate_science_policy(state)
        self.assertEqual((state["phase"], state["_next_step"]), ("reviewing", "reviewing"))
        self.assertTrue(state["review_preflight"])
        self.assertEqual(state["pending_search_queries"], [])
        self.assertEqual(state["legacy_analysis_search_queries"], ["old missing evidence"])
        self.assertEqual((state["analysis_search_round"], state["iteration"], state["max_iterations"]), (2, 2, 3))
        self.assertEqual(state["science_retrieval"], prior)
        self.assertEqual(state["review_search_round"], 1)
        self.assertEqual(state["research_profile"]["max_analysis_search_rounds"], 0)

    def test_legacy_review_search_keeps_claims_and_returns_via_analysis(self):
        state = fixture_state(1)
        add_papers(state, 1)
        claim(state)
        original = copy.deepcopy(state["claims"])
        state.update(phase="re_researching", _next_step="re_researching", supplementary_origin="critic",
                     return_phase="revising", pending_search_queries=["existing authorized query"], iteration=2)
        migrate_science_policy(state)
        self.assertEqual(state["_next_step"], "re_researching")
        self.assertEqual(state["return_phase"], "analyzing")
        self.assertEqual(state["analysis_continuation"], "revising")
        self.assertEqual(state["claims"], original)
        self.assertEqual(state["pending_search_queries"], ["existing authorized query"])
        self.assertEqual(state["iteration"], 2)

    def test_policy_migration_leaves_industry_state_unchanged(self):
        state = fixture_state(1)
        state["research_profile"] = {"mode": "industry", "profile_id": "industry"}
        state.update(phase="re_researching", supplementary_origin="analysis", iteration=2)
        before = copy.deepcopy(state)
        migrate_science_policy(state)
        self.assertEqual(state, before)


class PhaseRoutingTests(unittest.IsolatedAsyncioTestCase):
    def graph(self, callbacks):
        graph = DeepResearchGraph.__new__(DeepResearchGraph)
        graph.checkpoint_service = Mock()
        graph.checkpoint_service.load_full_checkpoint.return_value = None
        order, snapshots = [], []
        graph._save_checkpoint = lambda state, *args: snapshots.append(
            copy.deepcopy({key: value for key, value in state.items() if key != "_message_queue"})) or True
        for name, callback in callbacks.items():
            async def run(state, name=name, callback=callback):
                order.append((name, state["phase"]))
                result = callback(state)
                if asyncio.iscoroutine(result):
                    await result
                return state
            setattr(graph, name, Mock(name=name, process=run))
        return graph, order, snapshots

    async def run_graph(self, graph, state):
        with patch(GRAPH + ".is_research_cancelled", return_value=False), patch(GRAPH + ".clear_cancel_flag"):
            return [event async for event in graph._run_simplified(state)]

    async def test_supplement_refreshes_analysis_and_charts_then_revises_existing_claims(self):
        state = fixture_state(2)
        add_papers(state, 1)
        original = claim(state)
        original_id = original["claim_id"]
        state.update(phase="re_researching", _next_step="re_researching", supplementary_origin="critic",
                     return_phase="revising", final_report="Existing draft")

        def scout(st):
            add_papers(st, 3)
            st["phase"] = "analyzing"

        def writer(st):
            self.assertEqual(st["phase"], "revising")
            self.assertEqual(st["claims"][0]["claim_id"], original_id)
            self.assertTrue(st["evidence_assessment"]["sufficient"])
            self.assertEqual(st["corpus_statistics"]["paper_count"], 3)
            st["final_report"] = "Revised report from refreshed evidence"

        graph, order, snapshots = self.graph({
            "scout": scout, "data_analyst": lambda st: analyze_science(agent(), st),
            "wizard": lambda st: None, "writer": writer, "critic": lambda st: st.update(phase="completed"),
        })
        events = await self.run_graph(graph, state)
        self.assertEqual([name for name, _ in order], ["scout", "data_analyst", "wizard", "writer", "critic"])
        self.assertEqual(events[-1]["type"], "research_complete")
        self.assertFalse(any(event["type"] == "phase" and event["phase"] == "writing" for event in events))
        self.assertTrue(any(st["_next_step"] == "analyzing" for st in snapshots))

    async def test_no_readable_evidence_goes_to_review_before_wizard_or_writer(self):
        state = fixture_state(1)
        state.update(phase="analyzing", _next_step="analyzing", search_web=False, search_local=False)
        graph, order, _ = self.graph({
            "data_analyst": lambda st: analyze_science(agent(), st),
            "critic": lambda st: review_science(agent(), st),
            "wizard": lambda st: self.fail("No evidence must not create charts"),
            "writer": lambda st: self.fail("No evidence must not create a draft"),
        })
        events = await self.run_graph(graph, state)
        self.assertEqual([name for name, _ in order], ["data_analyst", "critic"])
        self.assertEqual(events[-1]["type"], "research_complete")
        self.assertIsNone(state["quality_score"])

    async def test_disconnect_saves_active_retrieval_queue_and_used_budget(self):
        state = fixture_state(1)
        state.update(phase="researching", _next_step="researching")
        started, stopped = asyncio.Event(), asyncio.Event()

        async def scout(st):
            st["science_retrieval"] = {"recursive_queries_used": 3, "requests_used": 9,
                                       "queue": [{"id": "pending_source", "status": "running", "charged": True}]}
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        graph, _, snapshots = self.graph({"scout": scout})
        running = asyncio.create_task(self.run_graph(graph, state))
        await asyncio.wait_for(started.wait(), timeout=3)
        running.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await running
        self.assertTrue(stopped.is_set())
        self.assertTrue(snapshots)
        self.assertEqual(snapshots[-1]["_next_step"], "researching")
        self.assertEqual(snapshots[-1]["science_retrieval"]["recursive_queries_used"], 3)
        self.assertEqual(snapshots[-1]["science_retrieval"]["requests_used"], 9)
        self.assertEqual(snapshots[-1]["science_retrieval"]["queue"][0]["id"], "pending_source")
        self.assertEqual(graph.checkpoint_service.update_status.call_args.args[1], "paused")

    async def test_cancel_after_scout_completes_preserves_new_evidence_and_budget(self):
        state = fixture_state(1)
        state.update(phase="researching", _next_step="researching")
        cancelled = False

        def scout(st):
            nonlocal cancelled
            add_papers(st, 1)
            st["science_retrieval"] = {"requests_used": 9, "recursive_queries_used": 3, "queue": []}
            cancelled = True

        graph, _, snapshots = self.graph({"scout": scout})
        with patch(GRAPH + ".is_research_cancelled", side_effect=lambda _: cancelled), patch(GRAPH + ".clear_cancel_flag"):
            events = [event async for event in graph._run_simplified(state)]
        self.assertEqual(events[-1]["type"], "research_cancelled")
        self.assertTrue(snapshots, "Cancellation after Scout completion must save partial work")
        self.assertEqual(snapshots[-1]["science_retrieval"]["requests_used"], 9)
        self.assertEqual(len(snapshots[-1]["papers"]), 1)
        self.assertEqual(snapshots[-1]["_next_step"], "analyzing")

    async def test_cancel_after_wizard_keeps_revision_continuation(self):
        state = fixture_state(1)
        add_papers(state, 1)
        claim(state)
        state.update(phase="analyzing", _next_step="analyzing", analysis_continuation="revising")
        cancelled = False

        def wizard(st):
            nonlocal cancelled
            cancelled = True

        graph, _, snapshots = self.graph({"data_analyst": lambda st: st.update(phase="analyzing"), "wizard": wizard})
        with patch(GRAPH + ".is_research_cancelled", side_effect=lambda _: cancelled), patch(GRAPH + ".clear_cancel_flag"):
            events = [event async for event in graph._run_simplified(state)]
        self.assertEqual(events[-1]["type"], "research_cancelled")
        self.assertTrue(snapshots)
        self.assertEqual(snapshots[-1]["_next_step"], "revising")


if __name__ == "__main__":
    unittest.main(verbosity=2)
