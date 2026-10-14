"""Offline regressions for Analysis-owned scientific hypothesis verification.

Retrieval/model replies are fixtures. No network requests or research history writes.
"""
import asyncio
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_science_engine import fixture_state, paper, add_papers, agent
from config.research_profiles import get_research_profile
from service.deep_research_v2.agents.data_analyst import DataAnalyst
from service.deep_research_v2.evidence import register_evidence
from service.deep_research_v2.science_roles import scout_science, analyze_science, visualize_science

ROLE = "service.deep_research_v2.science_roles"
COLLECT = "service.deep_research_v2.science_retrieval.collect_scientific_evidence"


def hypothesis(state, name="hyp_1"):
    row = {"id": name, "content": "不同方法的适用条件存在差异", "status": "pending"}
    state["hypotheses"].append(row)
    return row


def reflection(state, status="supported", **extra):
    ids = list(state["evidence_ledger"])
    return {"hypotheses": [{"id": "hyp_1", "status": status, "evidence_ids": ids,
                            "reason": "依据已提供摘要中的方法适用条件"}],
            "insights": [{"text": "方法需要结合适用条件比较", "evidence_ids": ids}],
            "critical_gaps": [], "limitations": [], **extra}


class ScoutHypothesisStageTests(unittest.IsolatedAsyncioTestCase):
    async def test_verification_runs_once_after_web_recursion_and_local_retrieval(self):
        state = fixture_state(1)
        state.update(phase="researching", search_local=True)
        hypothesis(state)
        scout, analyst = agent(), agent()
        scout.name, analyst.name = "DeepScout", "DataAnalyst"
        order = []

        async def collect(_agent, st, **_kwargs):
            add_papers(st, 2)
            order.append("web_and_recursive_evidence")

        async def local(*_args, **_kwargs):
            order.append("local_evidence")
            return [paper(8, content="Local full text describes study conditions. " * 6,
                          document_id="fixture-doc", chunk_id="fixture-chunk")]

        async def verify(caller, prompt, **_kwargs):
            self.assertIs(caller, analyst)
            self.assertEqual(order, ["web_and_recursive_evidence", "local_evidence"])
            self.assertEqual(len(state["evidence_ledger"]), 3)
            for record in state["evidence_ledger"].values():
                self.assertIn(record["evidence_id"], prompt)
            order.append("verify")
            return reflection(state, "mixed")

        scout._execute_local_search = AsyncMock(side_effect=local)
        with patch(COLLECT, new_callable=AsyncMock, side_effect=collect), \
             patch(ROLE + ".json_call", new_callable=AsyncMock, side_effect=verify) as model:
            await scout_science(scout, state)
            model.assert_not_awaited()
            await analyze_science(analyst, state)
        model.assert_awaited_once()
        self.assertEqual(state["hypotheses"][0]["status"], "mixed")
        self.assertEqual(state["corpus_statistics"]["paper_count"], 3)
        self.assertEqual(state["corpus_statistics"]["year_distribution"], {"2020": 1, "2021": 2})
        self.assertFalse(state.get("pending_search_queries"))
        self.assertEqual(state["phase"], "analyzing")
        events = [(call.args[1], call.args[2]) for call in analyst.add_message.call_args_list]
        hypothesis_event = next(i for i, (kind, _) in enumerate(events) if kind == "hypotheses")
        completion = next(i for i, (kind, payload) in enumerate(events)
                          if kind == "research_step" and payload.get("status") == "completed")
        self.assertLess(hypothesis_event, completion)

    async def test_review_supplement_rechecks_hypotheses_and_clears_resolved_gaps(self):
        state = fixture_state(1)
        add_papers(state, 1)
        hypothesis(state)
        scout = agent()
        first_reply = reflection(state, critical_gaps=[{
            "kind": "topic_coverage", "description": "缺少数据集描述",
            "user_requirement_quote": "科学研究问题"}], limitations=["旧轮次局限"])
        with patch(COLLECT, new_callable=AsyncMock), \
             patch(ROLE + ".json_call", new_callable=AsyncMock, return_value=first_reply):
            await scout_science(scout, state)
            await analyze_science(agent(), state)
        self.assertFalse(state["evidence_assessment"]["sufficient"])
        self.assertEqual(state["hypotheses"][0]["status"], "supported")
        state.update(phase="re_researching", return_phase="analyzing", supplementary_origin="critic",
                     pending_search_queries=["Review-authorized missing dataset evidence"], iteration=1)

        async def collect(_agent, st, **kwargs):
            self.assertTrue(kwargs["supplementary"])
            register_evidence(st, paper(2))

        async def verify(*_args, **_kwargs):
            return reflection(state, "mixed")

        with patch(COLLECT, new_callable=AsyncMock, side_effect=collect), \
             patch(ROLE + ".json_call", new_callable=AsyncMock, side_effect=verify) as model:
            await scout_science(scout, state)
            await analyze_science(agent(), state)
            await visualize_science(agent(), state)
        model.assert_awaited_once()
        self.assertEqual(state["hypotheses"][0]["status"], "mixed")
        self.assertEqual(len(state["hypotheses"][0]["evidence_ids"]), 2)
        self.assertTrue(state["evidence_assessment"]["sufficient"])
        self.assertEqual(state["evidence_assessment"]["topic_gaps"], [])
        self.assertEqual(state["evidence_assessment"]["limitations"], [])
        self.assertEqual(state["iteration"], 1)
        self.assertEqual(state["supplementary_origin"], "critic")
        self.assertEqual({chart["id"] for chart in state["charts"]}, {"corpus_years", "corpus_methods"})
        self.assertEqual(sum(state["charts"][0]["data"].values()), 2)

    async def test_analyst_reassesses_restored_evidence_without_resetting_budget(self):
        state = fixture_state(1)
        add_papers(state, 1)
        hypothesis(state)
        reply = reflection(state, "insufficient", critical_gaps=[{
            "kind": "topic_coverage", "description": "缺少数据集描述",
            "user_requirement_quote": "科学研究问题"}], limitations=["仅取得摘要"])
        with patch(COLLECT, new_callable=AsyncMock), \
             patch(ROLE + ".json_call", new_callable=AsyncMock, return_value=reply):
            await scout_science(agent(), state)
        restored = json.loads(json.dumps(state))
        before = copy.deepcopy(restored)
        with patch(ROLE + ".json_call", new_callable=AsyncMock, return_value=reply) as model:
            await analyze_science(agent(), restored)
        model.assert_awaited_once()
        self.assertEqual(restored["hypotheses"][0]["status"], "insufficient")
        self.assertEqual(restored["research_profile"], before["research_profile"])
        self.assertEqual(restored["evidence_assessment"]["topic_gaps"], ["缺少数据集描述"])
        self.assertEqual(restored["evidence_assessment"]["limitations"], ["仅取得摘要"])
        self.assertTrue(restored.get("pending_search_queries"))
        self.assertEqual(restored["iteration"], before["iteration"])

    async def test_failed_verification_does_not_reuse_old_supported_results(self):
        state = fixture_state(1)
        add_papers(state, 1)
        row = hypothesis(state)
        row.update(status="supported", evidence_ids=list(state["evidence_ledger"]))
        state.update(insights=["Old insight"], research_insights=[{"text": "Old insight"}])
        with patch(COLLECT, new_callable=AsyncMock), \
             patch(ROLE + ".json_call", new_callable=AsyncMock, side_effect=ValueError("fixture model failure")):
            await scout_science(agent(), state)
            await analyze_science(agent(), state)
        self.assertEqual(row["status"], "insufficient")
        self.assertEqual(row["evidence_ids"], [])
        self.assertEqual(state["research_insights"], [])
        self.assertTrue(any("假设验证未完成" in error for error in state["errors"]))
        self.assertEqual(state["phase"], "completed")
        self.assertEqual(state["stop_reason"], "analysis_unavailable")

    async def test_missing_hypothesis_and_unknown_evidence_are_not_supported(self):
        state = fixture_state(1)
        add_papers(state, 1)
        hypothesis(state)
        hypothesis(state, "hyp_2").update(status="supported", evidence_ids=list(state["evidence_ledger"]))
        reply = {"hypotheses": [{"id": "hyp_1", "status": "supported", "evidence_ids": ["unknown"]}]}
        with patch(COLLECT, new_callable=AsyncMock), \
             patch(ROLE + ".json_call", new_callable=AsyncMock, return_value=reply):
            await scout_science(agent(), state)
            await analyze_science(agent(), state)
        self.assertEqual([row["status"] for row in state["hypotheses"]], ["insufficient", "insufficient"])
        self.assertTrue(all(not row["evidence_ids"] for row in state["hypotheses"]))

    async def test_metadata_only_skips_semantic_model_and_retrieves_before_writing(self):
        state = fixture_state(1)
        state["papers"] = [register_evidence(state, paper(1, abstract="", content="", evidence_level="metadata"))]
        hypothesis(state).update(status="supported")
        with patch(COLLECT, new_callable=AsyncMock), patch(ROLE + ".json_call", new_callable=AsyncMock) as model:
            await scout_science(agent(), state)
            await analyze_science(agent(), state)
        model.assert_not_awaited()
        self.assertEqual(state["hypotheses"][0]["status"], "insufficient")
        self.assertEqual(state["phase"], "re_researching")
        self.assertFalse(state["review_preflight"])
        self.assertTrue(state.get("pending_search_queries"))

    async def test_cancellation_during_verification_does_not_complete_analysis(self):
        state = fixture_state(1)
        add_papers(state, 1)
        scout = agent()
        with patch(COLLECT, new_callable=AsyncMock), \
             patch(ROLE + ".json_call", new_callable=AsyncMock, side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await analyze_science(scout, state)
        self.assertEqual(len(state["papers"]), 1)
        self.assertFalse(any(call.args[1] == "research_step" and call.args[2].get("status") == "completed"
                             for call in scout.add_message.call_args_list))

    async def test_industry_analyst_dispatch_is_unchanged(self):
        state = fixture_state()
        state.update(research_profile=get_research_profile("industry"), phase="analyzing")
        legacy = agent()
        legacy._analyze_data = AsyncMock(return_value=state)
        with patch(ROLE + ".verify_science_hypotheses", new_callable=AsyncMock) as verification:
            result = await DataAnalyst.process(legacy, state)
        legacy._analyze_data.assert_awaited_once_with(state)
        verification.assert_not_awaited()
        self.assertIs(result, state)


if __name__ == "__main__":
    unittest.main(verbosity=2)
