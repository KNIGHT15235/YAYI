"""Offline workflow durability/backpressure regressions; use the offline runner.

No real providers, Redis, database rows, or .env files are used by these tests.
"""
import asyncio
import copy
import json
import importlib
import unittest
from contextlib import aclosing
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from config.research_profiles import get_research_profile
from service.checkpoint_service import CheckpointService
from service.deep_research_v2 import graph as graph_module
from service.deep_research_v2.graph import DeepResearchGraph, ResearchEventQueue
from service.deep_research_v2.service import DeepResearchV2Service
from service.deep_research_v2.state import create_initial_state

research_router = importlib.import_module("router.research_router")


class AtomicMemoryCheckpoint:
    supports_atomic_status = True

    def __init__(self, fail=None):
        self.snapshots = []
        self.attempts = 0
        self.fail = fail or (lambda state, status: False)

    def save_checkpoint(self, session_id, state, user_id=None, ui_state=None,
                        final_report=None, status="running", error_message=None):
        self.attempts += 1
        if self.fail(state, status):
            return None
        clean = CheckpointService()._clean_state_for_storage(state)
        self.snapshots.append({"state_json": clean, "ui_state_json": copy.deepcopy(ui_state),
                               "status": status, "error_message": error_message})
        return "offline-checkpoint"

    def load_full_checkpoint(self, *args, **kwargs):
        return copy.deepcopy(self.snapshots[-1]) if self.snapshots else None

    def load_checkpoint(self, *args, **kwargs):
        return copy.deepcopy(self.snapshots[-1]["state_json"]) if self.snapshots else None

    def update_status(self, *args, **kwargs):
        raise AssertionError("An atomic adapter must not use a second terminal-status transaction")


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


def fixture(fail=None, science=False):
    graph = DeepResearchGraph.__new__(DeepResearchGraph)
    graph.max_iterations = 2
    graph.research_profile = get_research_profile("science" if science else "industry")
    graph.checkpoint_service = AtomicMemoryCheckpoint(fail)
    calls = []
    for name in ("architect", "scout", "data_analyst", "wizard", "writer", "critic"):
        setattr(graph, name, Agent(name, calls))
    graph.writer.action = lambda state: state.update(final_report="Evidence-based report")
    graph.critic.action = lambda state: state.update(phase="completed", outcome="passed",
                                                    review_verdict="pass", stop_reason="quality_passed")
    state = create_initial_state("offline research", "offline-runtime")
    state["research_profile"] = graph.research_profile
    return graph, state, calls


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cancelled = False
        self.patches = [patch.object(graph_module, "is_research_cancelled", side_effect=lambda _: self.cancelled),
                        patch.object(graph_module, "clear_cancel_flag")]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    async def run_graph(self, graph, state):
        return [event async for event in graph._run_simplified(state)]

    async def test_initial_snapshot_failure_never_starts_an_agent(self):
        graph, state, calls = fixture(lambda state, status: True)
        events = await self.run_graph(graph, state)
        self.assertEqual(calls, [])
        self.assertEqual(events[-1]["code"], "checkpoint_persistence_failed")
        self.assertFalse(events[-1]["checkpoint_saved"])
        self.assertNotIn("research_complete", [event["type"] for event in events])

    async def test_phase_snapshot_failure_prevents_next_agent(self):
        graph, state, calls = fixture(lambda state, status: state.get("_next_step") == "analyzing")
        events = await self.run_graph(graph, state)
        self.assertEqual(calls, ["architect", "scout"])
        self.assertEqual(events[-1]["code"], "checkpoint_persistence_failed")
        self.assertEqual(graph.checkpoint_service.snapshots[-1]["state_json"]["_next_step"], "researching")

    async def test_final_snapshot_failure_never_emits_complete(self):
        graph, state, _ = fixture(lambda state, status: status == "completed")
        events = await self.run_graph(graph, state)
        self.assertEqual(events[-1]["code"], "checkpoint_persistence_failed")
        self.assertNotIn("completed", [row["status"] for row in graph.checkpoint_service.snapshots])
        self.assertNotIn("research_complete", [event["type"] for event in events])

    async def test_completion_snapshot_contains_terminal_state_and_budget_atomically(self):
        graph, state, _ = fixture()
        state["iteration"] = 2
        state["science_retrieval"] = {"requests_used": 9}
        events = await self.run_graph(graph, state)
        final = graph.checkpoint_service.snapshots[-1]
        self.assertEqual(final["status"], "completed")
        self.assertEqual(final["state_json"]["_next_step"], "completed")
        self.assertEqual(final["state_json"]["iteration"], 2)
        self.assertEqual(final["state_json"]["science_retrieval"]["requests_used"], 9)
        self.assertEqual(events[-1]["research_outcome"], "passed")
        self.assertEqual(events[-1]["review_verdict"], "pass")
        self.assertEqual(events[-1]["stop_reason"], "quality_passed")
        self.assertNotIn("_checkpoint_status", final["state_json"])

    async def test_disconnect_after_complete_does_not_downgrade_terminal_status(self):
        graph, state, _ = fixture()
        events = graph._run_simplified(state)
        async for event in events:
            if event["type"] == "research_complete":
                break
        await events.aclose()
        self.assertEqual(graph.checkpoint_service.snapshots[-1]["status"], "completed")
        self.assertNotIn("paused", [row["status"] for row in graph.checkpoint_service.snapshots])

    async def test_cancellation_save_failure_does_not_claim_saved(self):
        graph, state, _ = fixture(lambda state, status: status == "paused")
        self.cancelled = True
        events = await self.run_graph(graph, state)
        self.assertEqual(events[-1]["code"], "checkpoint_persistence_failed")
        self.assertNotIn("research_cancelled", [event["type"] for event in events])

    async def test_cancellation_after_start_event_is_not_erased_by_producer(self):
        graph, _, calls = fixture()

        def erase_flag(_):
            self.cancelled = False

        with patch.object(graph_module, "clear_cancel_flag", side_effect=erase_flag) as clear:
            async with aclosing(graph.run("offline", "offline-runtime")) as events:
                self.assertEqual((await events.__anext__())["type"], "research_start")
                self.cancelled = True
                tail = [event async for event in events]
        clear.assert_not_called()
        self.assertEqual(calls, [])
        self.assertEqual(tail[-1]["type"], "research_cancelled")

    async def test_slow_consumer_does_not_block_cancellation_or_pause_snapshot(self):
        graph, state, calls = fixture()
        state.update(phase="researching", _next_step="researching")
        agent_stopped = asyncio.Event()

        async def wait_for_cancel(st):
            try:
                await asyncio.Event().wait()
            finally:
                agent_stopped.set()

        graph.scout.action = wait_for_cancel
        async with aclosing(graph._run_simplified(state)) as events:
            self.assertEqual((await events.__anext__())["type"], "phase")
            self.assertEqual((await events.__anext__())["type"], "thought")
            self.cancelled = True
            # No further SSE pull happens before cancellation is observed.
            await asyncio.wait_for(agent_stopped.wait(), timeout=1.5)
            # Agent cleanup and durable pause are separate awaited operations.
            # One event-loop tick is not a cross-platform completion barrier.
            async def wait_for_snapshot():
                while not graph.checkpoint_service.snapshots:
                    await asyncio.sleep(.01)
            await asyncio.wait_for(wait_for_snapshot(), timeout=1.5)
            self.assertEqual(graph.checkpoint_service.snapshots[-1]["status"], "paused")
            tail = [event async for event in events]
        self.assertEqual(calls, ["scout"])
        self.assertEqual(tail[-1]["type"], "research_cancelled")

    async def test_critical_overflow_fails_visibly_and_keeps_queue_bounded(self):
        graph, state, _ = fixture()

        def flood(st):
            for number in range(400):
                st["_message_queue"].put_nowait({"type": "claim_verification", "number": number})

        graph.scout.action = flood
        events = await self.run_graph(graph, state)
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(graph.checkpoint_service.snapshots[-1]["status"], "failed")
        self.assertNotIn("research_complete", [event["type"] for event in events])

    async def test_science_analysis_search_returns_to_analysis_before_writer(self):
        graph, state, calls = fixture(science=True)
        state.update(phase="analyzing", _next_step="analyzing")
        graph.scout.action = lambda st: st.update(found=True)
        graph.data_analyst.action = lambda st: st.update(
            phase="analyzing" if st.get("found") else "re_researching", analysis_continuation="writing")
        with patch("service.deep_research_v2.science_roles.migrate_science_policy"):
            events = await self.run_graph(graph, state)
        self.assertEqual(calls, ["data_analyst", "scout", "data_analyst", "wizard", "writer", "critic"])
        self.assertEqual(events[-1]["type"], "research_complete")

    async def test_science_no_evidence_terminal_does_not_run_writer_or_critic(self):
        graph, state, calls = fixture(science=True)
        state.update(phase="analyzing", _next_step="analyzing")
        graph.data_analyst.action = lambda st: st.update(phase="completed", final_report="No readable evidence; no conclusions drawn.",
            outcome="insufficient_evidence", review_verdict="not_reviewed", stop_reason="no_readable_evidence")
        with patch("service.deep_research_v2.science_roles.migrate_science_policy"):
            events = await self.run_graph(graph, state)
        self.assertEqual(calls, ["data_analyst"])
        self.assertEqual(events[-1]["research_outcome"], "insufficient_evidence")
        self.assertEqual(events[-1]["review_verdict"], "not_reviewed")

    async def test_analysis_unavailable_stops_gracefully_but_persists_failed_step(self):
        graph, state, calls = fixture(science=True)
        state.update(phase="analyzing", _next_step="analyzing")
        graph.data_analyst.action = lambda st: st.update(phase="completed", final_report="Analysis unavailable; no factual writing.",
            outcome="completed_with_warnings", review_verdict="unconfirmed", stop_reason="analysis_unavailable",
            quality_review_note="Analysis service unavailable")
        with patch("service.deep_research_v2.science_roles.migrate_science_policy"):
            events = await self.run_graph(graph, state)
        snapshot = graph.checkpoint_service.snapshots[-1]
        self.assertEqual(snapshot["status"], "completed")
        step = next(item for item in snapshot["ui_state_json"]["research_steps"] if item["type"] == "analyzing")
        self.assertEqual(step["status"], "failed")
        self.assertEqual(calls, ["data_analyst"])
        self.assertEqual(events[-1]["research_outcome"], "completed_with_warnings")

    async def test_review_unavailable_terminal_preserves_failed_retry_step(self):
        graph, state, calls = fixture(science=True)
        state.update(phase="review_retry", _next_step="review_retry", review_retry_count=1, final_report="Unverified draft")
        graph.critic.action = lambda st: st.update(phase="completed", outcome="completed_with_warnings",
            review_verdict="unconfirmed", stop_reason="review_unavailable", quality_review_note="Review service unavailable")
        with patch("service.deep_research_v2.science_roles.migrate_science_policy"):
            events = await self.run_graph(graph, state)
        snapshot = graph.checkpoint_service.snapshots[-1]
        step = next(item for item in snapshot["ui_state_json"]["research_steps"] if item["type"] == "review_retry")
        self.assertEqual(step["status"], "failed")
        self.assertEqual(calls, ["critic"])
        self.assertEqual(events[-1]["research_outcome"], "completed_with_warnings")
        self.assertEqual(events[-1]["review_verdict"], "unconfirmed")

    async def test_bounded_review_retry_returns_to_same_critic_without_writer(self):
        graph, state, calls = fixture()
        state.update(phase="reviewing", _next_step="reviewing", final_report="Existing draft")

        def review(st):
            if not st.get("review_retry_count"):
                st.update(phase="review_retry", review_retry_count=1)
            else:
                st.update(phase="completed", outcome="passed", review_verdict="pass")

        graph.critic.action = review
        events = await self.run_graph(graph, state)
        self.assertEqual(calls, ["critic", "critic"])
        self.assertEqual(events[-1]["type"], "research_complete")

    async def test_resume_load_failure_never_resets_research(self):
        graph, _, calls = fixture()
        events = [event async for event in graph.run("ignored", "offline-runtime", resume=True)]
        self.assertEqual(calls, [])
        self.assertEqual(events[-1]["code"], "checkpoint_load_failed")
        self.assertEqual(graph.checkpoint_service.attempts, 0)

    async def test_ordinary_resume_persists_running_before_service_and_preserves_research_state(self):
        for status in ("paused", "failed"):
            with self.subTest(status=status):
                state = {"query": "offline", "version": "v2", "phase": "writing", "_next_step": "writing",
                         "knowledge_base_id": None, "search_local": False,
                         "iteration": 1, "max_iterations": 3, "analysis_search_round": 2,
                         "claims": [{"claim_id": "claim-existing", "claim_text": "saved claim"}],
                         "evidence_ledger": {"ev-existing": {"content": "saved evidence"}},
                         "science_retrieval": {"requests_used": 7}}
                full = {"query": "offline", "status": status, "error_message": "previous failure",
                        "state_json": copy.deepcopy(state), "ui_state_json": {"research_steps": ["saved"]},
                        "final_report": "Previously saved report"}
                lease = Mock(acquire=AsyncMock(), release=AsyncMock())
                lease.acquire.return_value = lease
                checkpoints = Mock(load_full_checkpoint=Mock(return_value=full),
                                   save_checkpoint=Mock(return_value="saved"))
                service = Mock(research=Mock(return_value="sse-source"))
                def build_service():
                    lease.acquire.assert_awaited_once()
                    checkpoints.save_checkpoint.assert_called_once()
                    self.assertEqual(checkpoints.save_checkpoint.call_args.kwargs["status"], "running")
                    return service
                with patch.object(research_router, "authorize_research_session"), \
                     patch.object(research_router, "ResearchLease", return_value=lease), \
                     patch.object(research_router, "get_checkpoint_service", return_value=checkpoints), \
                     patch.object(research_router, "get_research_service_v2", side_effect=build_service), \
                     patch.object(research_router, "clear_cancel_flag"), \
                     patch.object(research_router, "_response", side_effect=lambda source, _: source):
                    response = await research_router.resume_research("offline-resume", SimpleNamespace(id="owner"), Mock())
                self.assertEqual(response, "sse-source")
                saved = checkpoints.save_checkpoint.call_args
                self.assertEqual(saved.args[1], state)
                self.assertEqual(saved.kwargs["ui_state"], full["ui_state_json"])
                self.assertEqual(saved.kwargs["final_report"], full["final_report"])
                self.assertIsNone(saved.kwargs["error_message"])
                self.assertEqual(full["state_json"], state)
                service.research.assert_called_once_with(query="offline", session_id="offline-resume", resume=True, user_id="owner")
                lease.release.assert_not_awaited()  # StreamingResponse owns the lease after success.

    async def test_ordinary_resume_commit_failure_returns_503_without_starting_service(self):
        owner = "00000000-0000-0000-0000-000000000001"
        state = {"query": "offline", "version": "v2", "phase": "writing", "_next_step": "writing",
                 "knowledge_base_id": None, "search_local": False, "iteration": 1, "max_iterations": 3}
        full = {"status": "failed", "query": "offline", "state_json": copy.deepcopy(state),
                "ui_state_json": {}, "final_report": "saved report", "error_message": "previous failure"}
        database = Mock()
        database.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
            id="offline-checkpoint", user_id=owner)
        database.commit.side_effect = RuntimeError("offline commit failure")
        checkpoints = CheckpointService()
        checkpoints._get_db = lambda: database
        checkpoints.load_full_checkpoint = Mock(return_value=full)
        lease = Mock(acquire=AsyncMock(), release=AsyncMock())
        lease.acquire.return_value = lease
        with patch.object(research_router, "authorize_research_session"), \
             patch.object(research_router, "ResearchLease", return_value=lease), \
             patch.object(research_router, "get_checkpoint_service", return_value=checkpoints), \
             patch.object(research_router, "get_research_service_v2") as service_factory, \
             patch.object(research_router, "clear_cancel_flag") as clear:
            with self.assertRaises(HTTPException) as context:
                await research_router.resume_research("offline-resume", SimpleNamespace(id=owner), Mock())
        self.assertEqual(context.exception.status_code, 503)
        database.commit.assert_called_once()
        database.rollback.assert_called_once()
        service_factory.assert_not_called()
        clear.assert_not_called()
        lease.release.assert_awaited_once()
        self.assertEqual(full["state_json"], state)

    async def test_service_envelopes_every_json_event(self):
        service = DeepResearchV2Service.__new__(DeepResearchV2Service)

        async def run(*args, **kwargs):
            yield {"type": "phase", "phase": "analyzing"}
            yield {"type": "error", "content": "offline failure", "run_id": "wrong"}

        service.graph = SimpleNamespace(run=run)
        chunks = [chunk async for chunk in service.research("q", session_id="right")]
        payloads = [json.loads(chunk[len("data: "):]) for chunk in chunks if "[DONE]" not in chunk]
        self.assertTrue(all(item["run_id"] == item["session_id"] == "right" for item in payloads))

    async def test_existing_run_rejected_before_any_state_overwrite(self):
        checkpoints = Mock(get_checkpoint_info=Mock(return_value={"status": "completed"}))
        lease = Mock(acquire=AsyncMock(), release=AsyncMock())
        lease.acquire.return_value = lease
        with patch.object(research_router, "authorize_research_session"), \
             patch.object(research_router, "_validate_local", return_value=None), \
             patch.object(research_router, "ResearchLease", return_value=lease), \
             patch.object(research_router, "get_checkpoint_service", return_value=checkpoints):
            with self.assertRaises(HTTPException) as context:
                await research_router.stream_research(research_router.ResearchRequest(query="new", session_id="existing"),
                                                      current_user=SimpleNamespace(id="owner"), db=Mock())
        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(context.exception.detail["code"], "research_run_exists")
        checkpoints.save_checkpoint.assert_not_called()
        lease.release.assert_awaited_once()

    async def test_failed_existing_run_lookup_does_not_start_or_overwrite(self):
        checkpoints = Mock(get_checkpoint_info=Mock(side_effect=RuntimeError("offline storage failure")))
        lease = Mock(acquire=AsyncMock(), release=AsyncMock())
        lease.acquire.return_value = lease
        with patch.object(research_router, "authorize_research_session"), \
             patch.object(research_router, "_validate_local", return_value=None), \
             patch.object(research_router, "ResearchLease", return_value=lease), \
             patch.object(research_router, "get_checkpoint_service", return_value=checkpoints):
            with self.assertRaises(HTTPException) as context:
                await research_router.stream_research(research_router.ResearchRequest(query="new", session_id="existing"),
                                                      current_user=SimpleNamespace(id="owner"), db=Mock())
        self.assertEqual(context.exception.status_code, 503)
        checkpoints.save_checkpoint.assert_not_called()


class CheckpointStorageContractTests(unittest.TestCase):
    def test_real_save_method_commits_state_and_terminal_status_together(self):
        row = SimpleNamespace(id="offline-row", user_id=None)
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = row
        store = CheckpointService()
        store._get_db = lambda: db
        state = {"query": "offline", "phase": "completed", "_next_step": "completed", "iteration": 2,
                 "science_retrieval": {"requests_used": 7}, "_checkpoint_status": "completed"}
        result = store.save_checkpoint("offline", state, final_report="report", status="completed")
        self.assertEqual(result, "offline-row")
        db.commit.assert_called_once()
        self.assertEqual(row.status, "completed")
        self.assertEqual(row.state_json["_next_step"], "completed")
        self.assertEqual(row.state_json["science_retrieval"]["requests_used"], 7)
        self.assertNotIn("_checkpoint_status", row.state_json)
        self.assertEqual(row.final_report, "report")


class EventQueueTests(unittest.TestCase):
    def test_progress_is_disposable_but_critical_events_are_not_silently_dropped(self):
        queue = ResearchEventQueue(maxsize=2)
        queue.put_nowait({"type": "thought", "number": 1})
        queue.put_nowait({"type": "claim_verification", "number": 2})
        queue.put_nowait({"type": "literature_progress", "number": 3})
        queue.put_nowait({"type": "report_draft", "number": 4})
        self.assertEqual(queue.qsize(), 2)
        self.assertEqual(queue.dropped_progress, 2)
        self.assertEqual(queue.get_nowait()["number"], 2)
        self.assertEqual(queue.get_nowait()["number"], 4)

    def test_critical_only_overflow_is_explicit(self):
        queue = ResearchEventQueue(maxsize=1)
        queue.put_nowait({"type": "claim_verification"})
        with self.assertRaises(asyncio.QueueFull):
            queue.put_nowait({"type": "report_draft"})
        self.assertTrue(queue.critical_overflow)
        self.assertEqual(queue.qsize(), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
