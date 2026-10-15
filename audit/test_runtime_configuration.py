"""Offline model-selection and Redis-database contracts; no provider calls."""
import copy
import os
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

from config.llm_config import AgentsConfig, LLMConfig, resolve_agent_model
from config.research_profiles import get_research_profile
from service.deep_research_v2 import graph as graph_module
from service.deep_research_v2.graph import DeepResearchGraph
from service.deep_research_v2.state import create_initial_state
from service.research_guard import ResearchLease


ROLES = ("architect", "scout", "data_analyst", "wizard", "writer", "critic")
EMPTY_MODEL_ENV = {"DEFAULT_MODEL": "", **{f"{role.upper()}_MODEL": "" for role in ROLES}}
DEFAULTS = dict(zip(ROLES, ("deepseek-v3.2", "qwen-plus", "qwen-plus",
                           "deepseek-v3.2", "deepseek-v3.2", "deepseek-v3.2")))


class ModelConfigurationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        environment = patch.dict(os.environ, EMPTY_MODEL_ENV)
        environment.start()
        self.addCleanup(environment.stop)

    def make_graph(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(graph_module, "get_config", return_value=LLMConfig()))
            stack.enter_context(patch.object(graph_module, "get_checkpoint_service", return_value=None))
            stack.enter_context(patch.object(graph_module, "LANGGRAPH_AVAILABLE", False))
            for constructor in ("ChiefArchitect", "DeepScout", "DataAnalyst", "CodeWizard", "LeadWriter", "CriticMaster"):
                stack.enter_context(patch.object(graph_module, constructor,
                    side_effect=lambda *args, **kwargs: SimpleNamespace(model=args[-1])))
            return DeepResearchGraph(llm_api_key="offline-fixture", profile_id="science")

    def test_no_override_keeps_existing_mixed_defaults(self):
        settings = AgentsConfig()
        self.assertEqual({role: getattr(settings, role).model for role in ROLES}, DEFAULTS)
        self.assertEqual(get_research_profile("science")["agent_models"], DEFAULTS)
        self.assertEqual(LLMConfig().default_model, "deepseek-v3.2")

    def test_explicit_default_and_role_overrides_reach_profile_and_constructor(self):
        with patch.dict(os.environ, {"DEFAULT_MODEL": "qwen-plus", "WRITER_MODEL": "writer-explicit",
                                     "CRITIC_MODEL": "critic-explicit"}):
            expected = {role: "qwen-plus" for role in ROLES}
            expected.update(writer="writer-explicit", critic="critic-explicit")
            graph = self.make_graph()
            self.assertEqual(LLMConfig().default_model, "qwen-plus")
            self.assertEqual({role: getattr(graph, role).model for role in ROLES}, expected)
            self.assertEqual(graph.research_profile["agent_models"], expected)
            self.assertEqual(get_research_profile("remote_sensing")["agent_models"], expected)

    async def test_new_and_resumed_runs_apply_explicit_overrides_and_record_actual_models(self):
        saved = create_initial_state("offline", "offline-models")
        saved["research_profile"] = get_research_profile("science")
        with patch.dict(os.environ, {"DEFAULT_MODEL": "qwen-plus", "DATA_ANALYST_MODEL": "analysis-explicit"}), \
             patch.object(graph_module, "get_config", return_value=LLMConfig()):
            expected = {role: "qwen-plus" for role in ROLES}
            expected["data_analyst"] = "analysis-explicit"
            for resume in (False, True):
                with self.subTest(resume=resume):
                    graph = self.make_graph()
                    graph._load_checkpoint = Mock(return_value=copy.deepcopy(saved))
                    snapshots = []
                    async def record(state):
                        snapshots.append(copy.deepcopy(state))
                        yield {"type": "offline-model-snapshot"}
                    graph._run_simplified = record
                    events = [event async for event in graph.run("offline", "offline-models", resume=resume)]
                    self.assertEqual(events[-1]["type"], "offline-model-snapshot")
                    self.assertEqual(snapshots[0]["research_profile"]["agent_models"], expected)
                    self.assertEqual({role: getattr(graph, role).model for role in ROLES}, expected)
        self.assertEqual(saved["research_profile"]["agent_models"], DEFAULTS)

    async def test_resume_without_explicit_override_preserves_all_saved_models(self):
        graph = self.make_graph()
        saved = create_initial_state("offline", "offline-models")
        saved["research_profile"] = get_research_profile("science")
        expected = {role: f"saved-{role}" for role in ROLES}
        saved["research_profile"]["agent_models"] = expected.copy()
        graph._load_checkpoint = Mock(return_value=saved)
        async def record(state):
            yield {"type": "offline-model-snapshot", "models": state["research_profile"]["agent_models"]}
        graph._run_simplified = record
        with patch.object(graph_module, "get_config", return_value=LLMConfig()):
            events = [event async for event in graph.run("offline", "offline-models", resume=True)]
        self.assertEqual(events[-1]["models"], expected)
        self.assertEqual({role: getattr(graph, role).model for role in ROLES}, expected)

    def test_unknown_explicit_model_is_not_silently_replaced(self):
        with patch.dict(os.environ, {"DEFAULT_MODEL": "qwen-plus", "WRITER_MODEL": " unavailable-model "}):
            self.assertEqual(resolve_agent_model("writer", "deepseek-v3.2"), "unavailable-model")


class ResearchLeaseConfigurationTests(unittest.TestCase):
    def test_lease_uses_explicit_redis_database(self):
        with patch.dict(os.environ, {"REDIS_DB": "9"}), \
             patch("service.research_guard.redis.Redis") as constructor:
            ResearchLease("offline-owner", "offline-run")
        self.assertEqual(constructor.call_args.kwargs["db"], 9)
        self.assertEqual(constructor.call_args.kwargs["socket_timeout"], .3)

    def test_lease_defaults_to_database_zero_when_unset(self):
        with patch.dict(os.environ), patch("service.research_guard.redis.Redis") as constructor:
            os.environ.pop("REDIS_DB", None)
            ResearchLease("offline-owner", "offline-run")
        self.assertEqual(constructor.call_args.kwargs["db"], 0)

    def test_injected_client_is_preserved(self):
        client = Mock()
        with patch("service.research_guard.redis.Redis") as constructor:
            self.assertIs(ResearchLease("offline-owner", "offline-run", client=client).client, client)
        constructor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
