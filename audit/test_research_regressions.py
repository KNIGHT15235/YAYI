"""Research regressions; external LLM/search/Redis are mocked, no user rows touched.

Run from project root: PYTHONPATH=backend/app python -m unittest discover -s audit -p test_research_regressions.py -v
"""
import asyncio
import copy
import importlib
from datetime import datetime
import json
import logging
import unittest
from unittest.mock import AsyncMock, Mock, patch

from service.checkpoint_service import CheckpointService
from service.deep_research_v2 import graph as graph_module
from service.deep_research_v2.graph import DeepResearchGraph
from service.deep_research_v2.service import DeepResearchV2Service
from service.deep_research_v2.state import create_initial_state
from service.deep_research_v2.agents.critic import CriticMaster
from service.deep_research_v2.agents.scout import DeepScout
from service.deep_research_v2.agents.wizard import CodeWizard
from service.react_controller import ReActController, ResearchPlan, SubQuery, Tool
research_router = importlib.import_module("router.research_router")


class MemoryCheckpoint:
    def __init__(self):
        self.state = None
        self.ui = None
        self.status = None

    def save_checkpoint(self, session_id, state, user_id=None, ui_state=None, final_report=None):
        self.state = CheckpointService()._clean_state_for_storage(state)
        self.ui = copy.deepcopy(ui_state)
        self.status = "running"
        return "audit-checkpoint"

    def load_checkpoint(self, session_id, user_id=None):
        return copy.deepcopy(self.state)

    def load_full_checkpoint(self, session_id, user_id=None):
        return {"state_json": self.state, "ui_state_json": copy.deepcopy(self.ui)}

    def update_status(self, session_id, status, error_message=None, user_id=None):
        self.status = status
        return True


class Agent:
    def __init__(self, name, calls, action=None):
        self.name = name
        self.calls = calls
        self.action = action

    async def process(self, state):
        self.calls.append((self.name, state["phase"]))
        state["_message_queue"].put_nowait({"type": "thought", "content": self.name})
        if self.action:
            self.action(state)
        return state


def make_graph(revise=False):
    graph = DeepResearchGraph.__new__(DeepResearchGraph)
    graph.max_iterations = 1
    graph.checkpoint_service = MemoryCheckpoint()
    calls = []
    graph.architect = Agent("architect", calls, lambda state: state.update(outline=[{"id": "s1"}]))
    graph.scout = Agent("scout", calls)
    graph.data_analyst = Agent("analyst", calls)
    graph.wizard = Agent("wizard", calls)
    def write(state):
        state["final_report"] = "revised" if state["phase"] == "revising" else "draft"
        state["phase"] = "reviewing"
    graph.writer = Agent("writer", calls, write)
    def review(state):
        if revise and state["iteration"] == 0:
            state.update(phase="revising", iteration=1)
        else:
            state.update(phase="completed", quality_score=8)
    graph.critic = Agent("critic", calls, review)
    return graph, calls


class ResearchRegressionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.redis_patch = patch.object(graph_module, "cache", Mock(get=Mock(return_value=None)))
        self.redis_patch.start()
        self.addCleanup(self.redis_patch.stop)

    def test_checkpoint_is_json_native_and_drops_runtime_queue(self):
        state = {"when": datetime(2026, 1, 1), "_message_queue": asyncio.Queue(),
                 "nested": {"when": datetime(2026, 1, 2)}, "_next_step": "reviewing"}
        clean = CheckpointService()._clean_state_for_storage(state)
        json.dumps(clean)
        self.assertNotIn("_message_queue", clean)
        self.assertEqual(clean["_next_step"], "reviewing")
        self.assertIsInstance(clean["nested"]["when"], str)

    def test_cancel_uses_redis_after_router_import(self):
        graph_module.cache.get.return_value = {"cancelled": True}
        self.assertTrue(graph_module.is_research_cancelled("audit"))
        graph_module.cache.get.assert_called_with("research:cancel:audit")

    async def test_six_agents_revision_final_review_and_final_checkpoint(self):
        graph, calls = make_graph(revise=True)
        events = [event async for event in graph.run("test", "audit")]
        self.assertEqual([name for name, _ in calls], ["architect", "scout", "analyst", "wizard", "writer", "critic", "writer", "critic"])
        self.assertEqual(events[-1]["final_report"], "revised")
        self.assertEqual(graph.checkpoint_service.state["final_report"], "revised")
        self.assertEqual(graph.checkpoint_service.state["phase"], "completed")
        self.assertEqual(graph.checkpoint_service.status, "completed")

    async def test_invalid_second_review_finishes_sse_and_saves_revised_report_without_score(self):
        for invalid_score in (0, 80):
            with self.subTest(invalid_score=invalid_score):
                graph, calls = make_graph()
                critic = CriticMaster.__new__(CriticMaster)
                critic.name, critic.logger = "CriticMaster", logging.getLogger("audit")
                dimensions = {key: 8.5 for key in CriticMaster.SCORE_WEIGHTS}
                first = {"overall_assessment": {"dimension_scores": dimensions},
                         "issues": [{"severity": "major", "issue_type": "logic_error"}]}
                invalid = {"overall_assessment": {"dimension_scores": {
                    **dimensions, "source_completeness": invalid_score}}, "issues": []}
                critic._review_content = AsyncMock(side_effect=[first, invalid, copy.deepcopy(invalid)])
                graph.critic = critic
                service = DeepResearchV2Service.__new__(DeepResearchV2Service)
                service.graph = graph
                chunks = [chunk async for chunk in service.research("test", "audit")]
                events = [json.loads(chunk.removeprefix("data: ").strip()) for chunk in chunks
                          if chunk.startswith("data: ") and "[DONE]" not in chunk]
                complete = next(event for event in events if event["type"] == "research_complete")
                self.assertFalse(any(event["type"] == "error" for event in events))
                self.assertEqual(critic._review_content.await_count, 3)
                self.assertEqual(complete["final_report"], "revised")
                self.assertIsNone(complete["quality_score"])
                self.assertEqual(complete["quality_dimensions"], {})
                self.assertEqual(complete["quality_review_status"], "unconfirmed")
                self.assertEqual(graph.checkpoint_service.state["final_report"], "revised")
                self.assertIsNone(graph.checkpoint_service.state["quality_score"])
                self.assertEqual(graph.checkpoint_service.status, "completed")
                self.assertTrue(any(event["type"] == "warning" and "质量待确认" in event.get("content", {}).get("content", "")
                                    for event in events))

    async def test_resume_skips_completed_steps_and_preserves_ui(self):
        graph, calls = make_graph()
        state = create_initial_state("test", "audit", search_web=False, search_local=True)
        state.update(phase="reviewing", _next_step="reviewing", final_report="saved report", kb_name="chosen")
        graph.checkpoint_service.state = state
        graph.checkpoint_service.ui = {"research_steps": [{"type": "planning", "status": "completed"}]}
        events = [event async for event in graph.run("ignored", "audit", resume=True)]
        self.assertEqual([name for name, _ in calls], ["critic"])
        self.assertEqual(events[0]["type"], "research_resumed")
        self.assertEqual(events[-1]["final_report"], "saved report")
        self.assertEqual(len(graph.checkpoint_service.ui["research_steps"]), 1)
        self.assertFalse(graph.checkpoint_service.state["search_web"])

    async def test_agent_failure_never_emits_completion(self):
        graph, calls = make_graph()
        graph.architect.process = AsyncMock(side_effect=RuntimeError("audit failure"))
        events = [event async for event in graph.run("test", "audit")]
        self.assertEqual(events[-1]["type"], "error")
        self.assertFalse(any(event["type"] == "research_complete" for event in events))
        self.assertEqual(graph.checkpoint_service.status, "failed")
        self.assertEqual(calls, [])

    async def test_cancellation_during_agent_stops_and_pauses(self):
        graph, calls = make_graph()
        async def wait_for_cancel(state):
            graph_module.cache.get.return_value = {"cancelled": True}
            await asyncio.sleep(10)
        graph.architect.process = AsyncMock(side_effect=wait_for_cancel)
        events = [event async for event in graph.run("test", "audit")]
        self.assertEqual(events[-1]["type"], "research_cancelled")
        self.assertEqual(graph.checkpoint_service.status, "paused")
        self.assertEqual(calls, [])

    async def test_closing_sse_service_cancels_nested_graph_agent(self):
        graph, calls = make_graph()
        cancelled = asyncio.Event()
        async def blocking(state):
            state["_message_queue"].put_nowait({"type": "thought", "content": "started"})
            try:
                await asyncio.sleep(60)
            finally:
                cancelled.set()
        graph.architect.process = AsyncMock(side_effect=blocking)
        service = DeepResearchV2Service.__new__(DeepResearchV2Service)
        service.graph = graph
        stream = service.research("audit", "audit")
        while "started" not in await stream.__anext__():
            pass
        await stream.aclose()
        self.assertTrue(cancelled.is_set())
        self.assertEqual(graph.checkpoint_service.status, "paused")

    async def test_sync_entry_runs_analysis_and_writing(self):
        graph, calls = make_graph()
        state = await graph.run_sync("test", "audit")
        self.assertEqual(state["phase"], "completed")
        self.assertIn(("analyst", "analyzing"), calls)
        self.assertIn(("writer", "writing"), calls)

    async def test_critic_reviews_revised_report_not_stale_sections(self):
        critic = CriticMaster.__new__(CriticMaster)
        critic.logger = logging.getLogger("audit")
        critic.call_llm = AsyncMock(return_value='{"overall_assessment":{"verdict":"pass"}}')
        state = create_initial_state("test", "audit")
        state.update(final_report="CURRENT_REVISION", draft_sections={"s1": "STALE_DRAFT"})
        await critic._review_content(state)
        prompt = critic.call_llm.call_args.kwargs["user_prompt"]
        self.assertIn("CURRENT_REVISION", prompt)
        self.assertNotIn("STALE_DRAFT", prompt)

    async def test_scout_researches_every_section_with_three_at_a_time(self):
        scout = DeepScout.__new__(DeepScout)
        scout.name = "scout"
        scout.logger = logging.getLogger("audit")
        scout.add_message = Mock()
        scout._fetch_stock_data_if_relevant = AsyncMock()
        scout._emit_search_results_event = Mock()
        scout._research_section = AsyncMock()
        state = create_initial_state("test", "audit")
        state["phase"] = "planning"
        state["outline"] = [{"id": str(i), "status": "pending"} for i in range(7)]
        await scout.process(state)
        self.assertEqual(scout._research_section.await_count, 7)

    async def test_local_search_uses_selected_kb_and_formats_result(self):
        scout = DeepScout.__new__(DeepScout)
        scout.logger = logging.getLogger("audit")
        scout.milvus_service = object()
        result = [{"document_id": "doc1", "document_name": "test.txt", "content_with_weight": "evidence", "score": .9}]
        with patch("service.retrieval_service.retrieve_from_knowledge_base", return_value=result) as retrieve:
            found = await scout._execute_local_search("query", kb_name="chosen")
        retrieve.assert_called_once_with("chosen", "query", 10)
        self.assertEqual(found[0]["title"], "test.txt")
        self.assertEqual(found[0]["summary"], "evidence")

    async def test_explicitly_disabled_search_never_enables_network_or_retrieval(self):
        scout = DeepScout.__new__(DeepScout)
        scout.name = "scout"
        scout.logger = logging.getLogger("audit")
        scout.add_message = Mock()
        scout._emit_search_results_event = Mock()
        scout._fetch_stock_data_if_relevant = AsyncMock()
        scout._research_section = AsyncMock()
        scout._execute_search = AsyncMock()
        scout._execute_local_search = AsyncMock()
        state = create_initial_state("test", "audit", search_web=False, search_local=False)
        state.update(phase="planning", outline=[{"id": "s1", "status": "pending"}],
                     pending_search_queries=["missing"])
        await scout.process(state)
        await scout._supplementary_research(state)
        await scout._execute_deep_search(state, "s1", ["source"], "source_tracing", [])
        self.assertFalse(state["search_web"])
        self.assertFalse(state["search_local"])
        scout._fetch_stock_data_if_relevant.assert_not_awaited()
        scout._research_section.assert_not_awaited()
        scout._execute_search.assert_not_awaited()
        scout._execute_local_search.assert_not_awaited()

    async def test_router_passes_iterations_and_search_flags_to_v2(self):
        service = Mock()
        async def research(**kwargs):
            service.received = kwargs
            yield "data: [DONE]\n\n"
        service.research = research
        lease = Mock(acquire=AsyncMock(), release=AsyncMock())
        lease.acquire.return_value = lease
        lease.stream = lambda source: source
        with patch.object(research_router, "get_research_service_v2", return_value=service) as factory, \
             patch.object(research_router, "ResearchLease", return_value=lease), \
             patch.object(research_router, "get_checkpoint_service", return_value=MemoryCheckpoint()), \
             patch.object(research_router, "_validate_local"):
            request = research_router.ResearchRequest(query="audit", max_iterations=1, search_modes=["local"], kb_name="chosen")
            response = await research_router.stream_research(request, current_user=Mock(id="audit-user"), db=Mock())
            _ = [chunk async for chunk in response.body_iterator]
            factory.assert_called_once_with(1)
        self.assertFalse(service.received["search_web"])
        self.assertTrue(service.received["search_local"])
        self.assertEqual(service.received["kb_name"], "chosen")

    async def test_supplementary_and_recursive_search_respect_local_only(self):
        scout = DeepScout.__new__(DeepScout)
        scout.name = "scout"
        scout.logger = logging.getLogger("audit")
        scout.add_message = Mock()
        scout._emit_search_results_event = Mock()
        scout._execute_search = AsyncMock(return_value=[])
        scout._execute_local_search = AsyncMock(return_value=[])
        state = create_initial_state("test", "audit", search_web=False, search_local=True)
        state.update(kb_name="chosen", pending_search_queries=["missing"])
        await scout._supplementary_research(state)
        await scout._execute_deep_search(state, "s1", ["source"], "source_tracing", [])
        scout._execute_search.assert_not_awaited()
        self.assertEqual(scout._execute_local_search.await_count, 2)

    async def test_react_plan_parallel_tools_reflection_and_completion(self):
        controller = ReActController.__new__(ReActController)
        handler = AsyncMock(return_value=[{"title": "source", "content": "evidence"}])
        controller.tools = {"web_search": Tool("web_search", "search", {}, handler)}
        queries = [SubQuery("one", "coverage", "web_search"), SubQuery("two", "coverage", "web_search")]
        controller._generate_plan = AsyncMock(return_value=ResearchPlan("understood", queries, "search", ["coverage"]))
        controller._reflect = AsyncMock(return_value={"coverage_analysis": "covered", "confidence": .9,
                                                      "is_sufficient": True, "additional_queries": []})
        events = [event async for event in controller.run("test")]
        self.assertEqual(handler.await_count, 2)
        self.assertEqual(events[-1]["type"], "react_complete")
        self.assertEqual(events[-1]["executed_queries"], ["one", "two"])
        self.assertEqual(len(events[-1]["collected_data"]), 2)

    def test_iteration_limits_reject_invalid_values(self):
        for invalid in (0, -1, 6):
            with self.assertRaises(ValueError):
                research_router.ResearchRequest(query="audit", max_iterations=invalid)

    async def test_wizard_generates_chart_without_llm_or_file_output(self):
        wizard = CodeWizard.__new__(CodeWizard)
        wizard.logger = logging.getLogger("audit")
        wizard._save_debug_log = Mock()
        wizard._save_debug_info = Mock()
        result = await wizard._execute_code("plt.plot([1, 2, 3], [2, 4, 6])")
        self.assertTrue(result["success"], result.get("error"))
        self.assertTrue(result["charts"])
        self.assertTrue(result["charts"][0].startswith("iVBOR"))


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main(verbosity=2)
