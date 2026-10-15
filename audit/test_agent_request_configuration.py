"""Verify real request parameters and evidence-bound chart design with fake SDK responses."""
import asyncio
import copy
import json
import os
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

from config.llm_config import LLMConfig
from service.deep_research_v2 import graph as graph_module
from service.deep_research_v2 import science_roles as science
from service.deep_research_v2 import science_retrieval as retrieval
from service.deep_research_v2.agents import (
    ChiefArchitect, DeepScout, DataAnalyst, CodeWizard, LeadWriter, CriticMaster,
)
from service.deep_research_v2.agents import base as base_module
from service.deep_research_v2.evidence import normalize_paragraph
from test_science_engine import fixture_state, add_papers
from test_industry_revision_integrity import report, state as industry_state


EXPECTED = {
    "architect": ("deepseek-v3.2", .3, 16000),
    "scout": ("qwen-plus", .2, 8000),
    "data_analyst": ("qwen-plus", .2, 8000),
    "wizard": ("deepseek-v3.2", .1, 6000),
    "writer": ("deepseek-v3.2", .4, 16000),
    "critic": ("deepseek-v3.2", .2, 16000),
}


def sdk_client(**kwargs):
    create = Mock(return_value=SimpleNamespace(choices=[
        SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))
    ]))
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


class AgentRequestTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {
            "DEFAULT_MODEL": "", **{role.upper() + "_MODEL": "" for role in EXPECTED},
        }))
        self.config = LLMConfig()
        stack.enter_context(patch.object(base_module, "get_config", return_value=self.config))
        stack.enter_context(patch.object(graph_module, "get_config", return_value=self.config))
        stack.enter_context(patch.object(base_module, "OpenAI", side_effect=sdk_client))
        stack.enter_context(patch.object(graph_module, "get_checkpoint_service", return_value=None))
        stack.enter_context(patch.object(graph_module, "LANGGRAPH_AVAILABLE", False))
        stack.enter_context(patch("service.deep_research_v2.agents.scout.MILVUS_AVAILABLE", False))
        self.graph = graph_module.DeepResearchGraph(llm_api_key="offline-fixture")

    def respond(self, role, result):
        create = getattr(self.graph, role).client.chat.completions.create
        create.reset_mock()
        create.side_effect = None
        create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(result, ensure_ascii=False)))])
        return create

    def assert_request(self, create, role, temperature=None):
        self.assertTrue(create.called)
        model, default_temperature, tokens = EXPECTED[role]
        for call in create.call_args_list:
            self.assertEqual(call.kwargs["model"], model)
            self.assertEqual(call.kwargs["temperature"], default_temperature if temperature is None else temperature)
            self.assertEqual(call.kwargs["max_tokens"], tokens)
            self.assertEqual(call.kwargs["response_format"], {"type": "json_object"})

    async def test_each_graph_agent_and_json_wrapper_send_configured_parameters(self):
        for role in EXPECTED:
            with self.subTest(role=role):
                worker = getattr(self.graph, role)
                create = self.respond(role, {"ok": True})
                await worker.call_llm("Output JSON", "offline")
                await science.json_call(worker, "offline JSON")
                self.assert_request(create, role)

    async def test_standalone_agents_use_same_defaults(self):
        for role, constructor in zip(EXPECTED, (
            ChiefArchitect, DeepScout, DataAnalyst, CodeWizard, LeadWriter, CriticMaster,
        )):
            with self.subTest(role=role):
                args = ["offline-fixture", "https://example.invalid/v1"]
                if role == "scout":
                    args.append("offline-search")
                worker = constructor(*args)
                await worker.call_llm("Output JSON", "offline")
                self.assert_request(worker.client.chat.completions.create, role)

    async def test_scientific_planning_analysis_writing_and_review_requests(self):
        st = fixture_state(1)
        planner = self.respond("architect", {"sections": [{"title": f"Section {i}"} for i in range(6)]})
        await science.plan_science(self.graph.architect, st)
        self.assert_request(planner, "architect")
        add_papers(st, 2)
        analyst = self.respond("data_analyst", {"critical_gaps": [], "limitations": [], "hypotheses": []})
        await science.analyze_science(self.graph.data_analyst, st)
        self.assert_request(analyst, "data_analyst")
        eid = st["papers"][0]["evidence_id"]
        writer = self.respond("writer", {"paragraphs": [
            {"text": "作者报告所研究的方法。", "evidence_ids": [eid]},
            {"text": "所提供的摘要限定了可以支持的结论范围。", "evidence_ids": [eid]},
        ]})
        await science.write_science(self.graph.writer, st)
        self.assert_request(writer, "writer")
        reviewer = self.respond("critic", {"results": []})
        await science.review_science(self.graph.critic, st)
        # An invalid verdict remains unconfirmed, but all requests still use the Reviewer config.
        self.assert_request(reviewer, "critic")
        self.assertNotEqual(st.get("quality_review_status"), "confirmed")

    async def test_supplementary_retrieval_temperature_does_not_leak_into_initial_search(self):
        st = fixture_state(1)
        add_papers(st, 1)
        data = retrieval.ensure_retrieval_state(st)
        node = {"query": st["query"]}
        for origin, temperature in (("supplementary", .1), ("initial", .2)):
            data["active_batch"] = {"origin": origin}
            create = self.respond("scout", {"followups": []})
            await retrieval._propose(self.graph.scout, st, node,
                                    [st["papers"][0]["evidence_id"]], retrieval.DEFAULT_LIMITS, 5)
            self.assert_request(create, "scout", temperature)

    async def test_industry_supplementary_extraction_uses_stage_temperature(self):
        create = self.respond("scout", {"extracted_facts": []})
        await self.graph.scout._analyze_supplementary_results("topic", "focused query", [])
        self.assert_request(create, "scout", .1)

    async def test_scientific_and_industry_revision_use_point_one(self):
        st = fixture_state(1)
        add_papers(st, 1)
        eid = st["papers"][0]["evidence_id"]
        claim = normalize_paragraph(st, "待修订观点。", [eid], "sec_1", 0)
        claim["verification_status"] = "insufficient"
        st["claims"] = [claim]
        create = self.respond("writer", {"revisions": [{
            "claim_id": claim["claim_id"], "text": "修订后的限定观点。", "evidence_ids": [eid],
        }]})
        await science.revise_science(self.graph.writer, st)
        self.assert_request(create, "writer", .1)
        original = report()
        create = self.respond("writer", {"revised_content": original, "changes_made": []})
        await self.graph.writer._revise_report(industry_state(original))
        self.assert_request(create, "writer", .1)
        create = self.respond("writer", {"ok": True})
        await self.graph.writer.call_llm("Output JSON", "next initial draft")
        self.assert_request(create, "writer", .4)

    def chart_state(self):
        st = fixture_state(1)
        add_papers(st, 4)
        science.corpus_analysis(st)
        return st

    async def test_wizard_calls_model_but_ignores_generated_values_and_code(self):
        st = self.chart_state()
        original = copy.deepcopy(st["corpus_statistics"])
        create = self.respond("wizard", {"charts": [
            {"id": "corpus_years", "type": "line", "orientation": "vertical", "data": [999999], "code": "forged"},
            {"id": "corpus_methods", "type": "bar", "orientation": "horizontal", "evidence_ids": ["fake"]},
        ]})
        await self.graph.wizard.process(st)
        self.assert_request(create, "wizard")
        self.assertEqual(st["visualization_plan"]["status"], "model")
        self.assertEqual(st["corpus_statistics"], original)
        years, methods = st["charts"]
        self.assertEqual(years["type"], "line")
        self.assertEqual(years["echarts_option"]["series"][0]["data"], list(original["year_distribution"].values()))
        self.assertEqual(methods["echarts_option"]["xAxis"]["type"], "value")
        self.assertEqual(methods["echarts_option"]["yAxis"]["data"], list(original["method_mentions"]))
        self.assertEqual(methods["evidence_ids"], [p["evidence_id"] for p in st["papers"]])
        self.assertNotIn("forged", json.dumps(st["code_executions"]))

    async def test_wizard_rejects_invalid_designs_and_records_fallback(self):
        for rows in ([], [None], [
            {"id": "corpus_years", "type": "line", "orientation": "vertical"},
            {"id": "corpus_methods", "type": "pie", "orientation": "vertical"},
        ], [
            {"id": "unknown", "type": "bar", "orientation": "vertical"},
            {"id": "corpus_methods", "type": "bar", "orientation": "vertical"},
        ]):
            with self.subTest(rows=rows):
                st = self.chart_state()
                self.respond("wizard", {"charts": rows})
                await self.graph.wizard.process(st)
                self.assertEqual(st["visualization_plan"]["status"], "deterministic_fallback")
                self.assertTrue(all(c["type"] == "bar" for c in st["charts"]))
                self.assertEqual(sum(st["charts"][0]["echarts_option"]["series"][0]["data"]), 4)

    async def test_wizard_provider_failure_falls_back_but_cancellation_propagates(self):
        create = self.respond("wizard", {"ok": True})
        create.side_effect = RuntimeError("offline provider failure")
        st = self.chart_state()
        await self.graph.wizard.process(st)
        self.assertEqual(st["visualization_plan"]["status"], "deterministic_fallback")
        create.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.graph.wizard.process(self.chart_state())

    async def test_wizard_skips_model_when_no_statistics_are_available(self):
        create = self.respond("wizard", {"ok": True})
        st = fixture_state()
        await self.graph.wizard.process(st)
        create.assert_not_called()
        self.assertEqual(st["visualization_plan"]["status"], "no_data")


if __name__ == "__main__":
    unittest.main()
