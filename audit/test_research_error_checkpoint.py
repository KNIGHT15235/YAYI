"""Offline failed-phase persistence and actual resume regressions; no user rows touched."""
import asyncio
import copy
import logging
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch

from dotenv import load_dotenv

PROJECT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT / "backend" / ".env")
sys.path.insert(0, str(PROJECT / "backend" / "app"))

from config.research_profiles import get_research_profile
from service.checkpoint_service import CheckpointService
from service.deep_research_v2 import graph as graph_module
from service.deep_research_v2.agents.scout import DeepScout
from service.deep_research_v2.graph import DeepResearchGraph
from service.deep_research_v2.state import create_initial_state


class MemoryCheckpoint:
    def __init__(self):
        self.state = None
        self.ui = None
        self.status = None
        self.error = None
        self.operations = []

    def save_checkpoint(self, session_id, state, user_id=None, ui_state=None, final_report=None):
        self.state = CheckpointService()._clean_state_for_storage(state)
        self.ui = copy.deepcopy(ui_state)
        self.status = "running"
        self.operations.append(("save", self.state["_next_step"], len(self.state.get("facts", []))))
        return "offline-checkpoint"

    def load_checkpoint(self, session_id, user_id=None):
        return copy.deepcopy(self.state)

    def load_full_checkpoint(self, session_id, user_id=None):
        return {"state_json": copy.deepcopy(self.state), "ui_state_json": copy.deepcopy(self.ui)} if self.state else None

    def update_status(self, session_id, status, error_message=None, user_id=None):
        self.status, self.error = status, error_message
        self.operations.append(("status", status))
        return True


class Agent:
    def __init__(self, name, calls, action=None):
        self.name, self.calls, self.action = name, calls, action

    async def process(self, state):
        self.calls.append(self.name)
        state["_message_queue"].put_nowait({"type": "thought", "content": self.name})
        if self.action:
            result = self.action(state)
            if asyncio.iscoroutine(result):
                await result
        return state


def make_graph():
    graph = DeepResearchGraph.__new__(DeepResearchGraph)
    graph.max_iterations = 2
    graph.research_profile = get_research_profile("industry")
    graph.checkpoint_service = MemoryCheckpoint()
    calls = []
    graph.architect = Agent("architect", calls, lambda st: st.update(outline=[
        {"id": "s1", "title": "市场", "status": "pending"},
        {"id": "s2", "title": "政策", "status": "pending"},
    ]))
    graph.scout = Agent("scout", calls)
    graph.data_analyst = Agent("analyst", calls)
    graph.wizard = Agent("wizard", calls)
    graph.writer = Agent("writer", calls, lambda st: st.update(final_report="Recovered evidence-based report"))
    graph.critic = Agent("critic", calls, lambda st: st.update(phase="completed", quality_score=8))
    return graph, calls


class FailedPhaseCheckpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cancel_patch = patch.object(graph_module, "cache", Mock(get=Mock(return_value=None)))
        self.cancel_patch.start()
        self.addCleanup(self.cancel_patch.stop)

    async def test_tail_failure_preserves_industry_evidence_and_real_scout_resume_skips_completed_sections(self):
        graph, calls = make_graph()
        scout = DeepScout.__new__(DeepScout)
        scout.name, scout.logger = "DeepScout", logging.getLogger("error-checkpoint-test")
        scout._fetch_stock_data_if_relevant = AsyncMock()
        scout._emit_search_results_event = Mock()

        async def section(st, item):
            item["status"] = "researching"  # Scout uses this after finishing section retrieval.
            st["facts"].append({"id": item["id"], "content": "Verified partial evidence " + item["id"],
                                "source_url": "https://example.test/" + item["id"], "source_name": item["title"]})

        scout._research_section = AsyncMock(side_effect=section)
        real_process = scout.process

        async def fail_after_retrieval(st):
            await real_process(st)
            st["data_points"].append({"metric": "already-acquired", "value": 2})
            raise TypeError("tail source statistics failed")

        scout.process = fail_after_retrieval
        graph.scout = scout
        events = [event async for event in graph.run("industry study", "offline-error", user_id="audit-user")]
        checkpoint = graph.checkpoint_service
        self.assertEqual(events[-1], {"type": "error", "content": "tail source statistics failed"})
        self.assertFalse(any(e["type"] == "research_complete" for e in events))
        self.assertEqual(checkpoint.status, "failed")
        self.assertEqual(checkpoint.state["_next_step"], "researching")
        self.assertEqual(len(checkpoint.state["facts"]), 2)
        self.assertEqual(len(checkpoint.ui["search_results"]), 2)
        self.assertEqual(checkpoint.state["data_points"][0]["value"], 2)
        self.assertTrue(all(s["status"] == "researching" for s in checkpoint.state["outline"]))
        self.assertEqual(checkpoint.operations[-2:], [("save", "researching", 2), ("status", "failed")])
        self.assertEqual(calls, ["architect"])

        # Resume through the public graph entry, with real DeepScout.process.
        # Completed sections retain their evidence instead of issuing searches again.
        scout.process = real_process
        resumed = [event async for event in graph.run("ignored", "offline-error", resume=True, user_id="audit-user")]
        self.assertEqual(resumed[0]["type"], "research_resumed")
        self.assertEqual(next(e["phase"] for e in resumed if e["type"] == "phase"), "researching")
        self.assertEqual(scout._research_section.await_count, 2)
        self.assertEqual(calls, ["architect", "analyst", "wizard", "writer", "critic"])
        self.assertEqual(len(checkpoint.state["facts"]), 2)
        self.assertEqual(checkpoint.status, "completed")
        self.assertEqual(resumed[-1]["type"], "research_complete")

    async def test_partial_supplement_resumes_its_saved_continuation_and_keeps_budget(self):
        graph, calls = make_graph()
        st = create_initial_state("industry study", "supplement-error")
        st.update(phase="re_researching", _next_step="re_researching", iteration=2,
                  research_profile=get_research_profile("industry"), return_phase="revising",
                  pending_search_queries=["missing policy evidence"], final_report="Existing draft")

        def fail(st):
            st["facts"].append({"id": "partial", "content": "Supplement acquired before failure", "source_url": "https://example.test/policy"})
            st["science_retrieval"] = {"requests_used": 7, "recursive_queries_used": 3,
                                       "queue": [{"id": "pending", "charged": True}]}
            raise RuntimeError("supplement failed")

        graph.scout = Agent("scout", calls, fail)
        events = [event async for event in graph._run_simplified(st)]
        checkpoint = graph.checkpoint_service
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(checkpoint.status, "failed")
        self.assertEqual(checkpoint.state["_next_step"], "re_researching")

        def recover(st):
            self.assertEqual(st["science_retrieval"]["requests_used"], 7)
            self.assertEqual(st["science_retrieval"]["recursive_queries_used"], 3)
            self.assertTrue(st["science_retrieval"]["queue"][0]["charged"])
            self.assertEqual(st["iteration"], 2)
            self.assertEqual(st["facts"][0]["id"], "partial")
            st["pending_search_queries"] = []

        graph.scout = Agent("scout", calls, recover)
        resumed = [event async for event in graph.run("ignored", "supplement-error", resume=True)]
        self.assertEqual(calls, ["scout", "scout", "writer", "critic"])
        self.assertEqual(checkpoint.state["_next_step"], "completed")
        self.assertEqual(resumed[-1]["type"], "research_complete")

    async def test_secondary_ui_snapshot_error_does_not_hide_original_agent_error(self):
        graph, calls = make_graph()

        def fail(st):
            st["facts"] = [None]  # UI snapshot cannot present this malformed entry.
            raise RuntimeError("original agent failure")

        graph.scout = Agent("scout", calls, fail)
        events = [event async for event in graph.run("industry study", "snapshot-error")]
        self.assertEqual(events[-1], {"type": "error", "content": "original agent failure"})
        self.assertEqual(graph.checkpoint_service.status, "failed")
        self.assertEqual(graph.checkpoint_service.error, "original agent failure")
        self.assertEqual(graph.checkpoint_service.state["facts"], [None])
        self.assertEqual(graph.checkpoint_service.state["_next_step"], "researching")
        self.assertFalse(any(e["type"] == "research_complete" for e in events))


if __name__ == "__main__":
    unittest.main(verbosity=2)
