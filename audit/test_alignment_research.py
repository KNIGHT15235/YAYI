"""Research alignment regressions; HTTP/LLM mocked, Redis checks use unique audit keys."""
import asyncio
import importlib
import json
import logging
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from dotenv import load_dotenv
PROJECT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT / "backend" / ".env")
sys.path.insert(0, str(PROJECT / "backend" / "app"))

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from core.database import get_db
from router.auth_router import get_current_user_required
from service.research_access import authorize_research_session
from service.research_guard import ResearchLease
from service.deep_research_v2 import safe_fetch
from service.deep_research_v2.agents import base as base_module
from service.deep_research_v2.agents import scout as scout_module
from service.deep_research_v2.agents.architect import ChiefArchitect
from service.deep_research_v2.agents.scout import DeepScout
from service.deep_research_v2.agents.critic import CriticMaster
from service.deep_research_v2.agents.data_analyst import DataAnalyst
from service.deep_research_v2.agents.wizard import CodeWizard
from service.deep_research_v2.state import create_initial_state
research_router = importlib.import_module("router.research_router")


def database_for(checkpoint=None, chat=None):
    db = Mock()
    q1, q2 = Mock(), Mock()
    q1.filter.return_value.first.return_value = checkpoint
    q2.filter.return_value.first.return_value = chat
    db.query.side_effect = [q1, q2]
    return db


class OwnershipTests(unittest.TestCase):
    def test_every_research_endpoint_requires_authentication(self):
        app = FastAPI()
        app.include_router(research_router.router)
        app.dependency_overrides[get_db] = lambda: Mock()
        client = TestClient(app)
        routes = [("post", "/research/stream", {"query": "audit"}),
                  ("get", "/research/stream?query=audit", None),
                  ("post", "/research/cancel/audit", None),
                  ("post", "/research/resume/audit", None),
                  ("get", "/research/checkpoint/audit", None),
                  ("get", "/research/checkpoint/audit/full", None),
                  ("get", "/research/checkpoints", None),
                  ("delete", "/research/checkpoint/audit", None),
                  ("get", "/research/test-wizard", None)]
        for method, url, body in routes:
            with self.subTest(url=url):
                result = client.request(method, url, json=body)
                self.assertEqual(result.status_code, 401)

    def test_owned_checkpoint_is_accessible(self):
        user_id, session_id = uuid.uuid4(), str(uuid.uuid4())
        cp = SimpleNamespace(user_id=user_id)
        self.assertIs(authorize_research_session(database_for(cp), str(user_id), session_id), cp)

    def test_unknown_foreign_and_unowned_legacy_sessions_are_hidden(self):
        owner, foreign, session_id = uuid.uuid4(), uuid.uuid4(), str(uuid.uuid4())
        cases = [(None, None), (SimpleNamespace(user_id=foreign), None),
                 (SimpleNamespace(user_id=None), None),
                 (SimpleNamespace(user_id=owner), SimpleNamespace(user_id=foreign))]
        for cp, chat in cases:
            with self.subTest(cp=cp, chat=chat), self.assertRaises(HTTPException) as raised:
                authorize_research_session(database_for(cp, chat), str(owner), session_id)
            self.assertEqual(raised.exception.status_code, 404)

    def test_legacy_checkpoint_claim_requires_owned_chat(self):
        owner, session_id = uuid.uuid4(), str(uuid.uuid4())
        cp = SimpleNamespace(user_id=None)
        db = database_for(cp, SimpleNamespace(user_id=owner))
        authorize_research_session(db, str(owner), session_id)
        self.assertEqual(cp.user_id, owner)
        db.commit.assert_called_once()

    def test_checkpoint_listing_is_scoped(self):
        app = FastAPI()
        app.include_router(research_router.router)
        app.dependency_overrides[get_current_user_required] = lambda: SimpleNamespace(id="audit-user")
        service = Mock()
        service.list_checkpoints.return_value = []
        with patch.object(research_router, "get_checkpoint_service", return_value=service):
            response = TestClient(app).get("/research/checkpoints")
        self.assertEqual(response.status_code, 200)
        service.list_checkpoints.assert_called_once_with(user_id="audit-user", status=None, limit=20)


class PublicFetchTests(unittest.TestCase):
    def addresses(self, host, port, **kwargs):
        value = host if host in {"127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1"} else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (value, port))]

    def test_private_loopback_metadata_and_invalid_schemes_are_blocked(self):
        urls = ["http://127.0.0.1", "http://10.0.0.1", "http://169.254.169.254/latest",
                "http://[::1]", "http://[fc00::1]", "file:///etc/passwd", "ftp://example.com",
                "https://user:password@example.com", "http://example.com:8000"]
        with patch.object(safe_fetch.socket, "getaddrinfo", side_effect=self.addresses):
            for url in urls:
                with self.subTest(url=url), self.assertRaises(ValueError):
                    safe_fetch.public_target(url)

    def test_dns_mixed_public_private_is_blocked(self):
        entries = self.addresses("example.com", 443) + self.addresses("127.0.0.1", 443)
        with patch.object(safe_fetch.socket, "getaddrinfo", return_value=entries), self.assertRaises(ValueError):
            safe_fetch.public_target("https://example.com")

    def test_public_https_pins_dns_and_validates_tls_hostname(self):
        response = Mock(status=200, headers={"Content-Type": "text/html; charset=utf-8"})
        response.stream.return_value = [b"<html>public evidence</html>"]
        pool = Mock()
        pool.request.return_value = response
        with patch.object(safe_fetch.socket, "getaddrinfo", side_effect=self.addresses), \
             patch.object(safe_fetch.urllib3, "HTTPSConnectionPool", return_value=pool) as constructor:
            html, url = safe_fetch.fetch_public_text("https://example.com/paper?q=1")
        self.assertIn("public evidence", html)
        constructor.assert_called_once_with("93.184.216.34", port=443, assert_hostname="example.com",
                                           server_hostname="example.com", cert_reqs="CERT_REQUIRED")
        self.assertFalse(pool.request.call_args.kwargs["redirect"])
        self.assertEqual(pool.request.call_args.kwargs["headers"]["Host"], "example.com")
        self.assertEqual(pool.request.call_args.args[1], "/paper?q=1")

    def test_redirect_to_private_address_is_rejected_before_second_request(self):
        response = Mock(status=302, headers={"Location": "http://127.0.0.1/private"})
        pool = Mock()
        pool.request.return_value = response
        with patch.object(safe_fetch.socket, "getaddrinfo", side_effect=self.addresses), \
             patch.object(safe_fetch.urllib3, "HTTPSConnectionPool", return_value=pool), \
             patch.object(safe_fetch.urllib3, "HTTPConnectionPool") as http_pool:
            with self.assertRaises(ValueError):
                safe_fetch.fetch_public_text("https://example.com")
        pool.request.assert_called_once()
        http_pool.assert_not_called()

    def test_oversize_response_is_not_read(self):
        response = Mock(status=200, headers={"Content-Type": "text/html", "Content-Length": str(safe_fetch.MAX_BYTES + 1)})
        pool = Mock()
        pool.request.return_value = response
        with patch.object(safe_fetch.socket, "getaddrinfo", side_effect=self.addresses), \
             patch.object(safe_fetch.urllib3, "HTTPSConnectionPool", return_value=pool), self.assertRaises(ValueError):
            safe_fetch.fetch_public_text("https://example.com")
        response.stream.assert_not_called()


class AgentAlignmentTests(unittest.IsolatedAsyncioTestCase):
    def test_review_model_is_independently_configurable(self):
        from config.llm_config import AgentsConfig
        with patch.dict(os.environ, {"CRITIC_MODEL": "audit-review-model"}):
            settings = AgentsConfig()
        self.assertEqual(settings.critic.model, "audit-review-model")
        self.assertEqual(settings.architect.model, "deepseek-v3.2")
        self.assertEqual(settings.scout.model, "qwen-plus")
        with patch.dict(os.environ):
            os.environ.pop("CRITIC_MODEL", None)
            self.assertEqual(AgentsConfig().critic.model, "qwen-plus")

    async def test_original_reading_budget_is_shared_by_parallel_sections(self):
        scout = DeepScout.__new__(DeepScout)
        scout.name, scout.logger, scout.add_message = "Scout", logging.getLogger("audit"), Mock()
        scout.deep_read_url = AsyncMock(return_value={"summary": "full original evidence"})
        state = create_initial_state("audit", "audit")
        groups = [[{"url": f"https://example.com/{group}/{i}"} for i in range(4)] for group in range(3)]
        await asyncio.gather(*(scout._enrich_with_originals(state, group) for group in groups))
        self.assertEqual(scout.deep_read_url.await_count, 3)
        self.assertEqual(len(state["raw_sources"]), 3)
        self.assertEqual(sum("original_reading" in item for group in groups for item in group), 3)

    async def test_original_reading_respects_offline_and_degrades_after_failure(self):
        scout = DeepScout.__new__(DeepScout)
        scout.name, scout.logger, scout.add_message = "Scout", logging.getLogger("audit"), Mock()
        scout.deep_read_url = AsyncMock(side_effect=TimeoutError())
        state = create_initial_state("audit", "audit", search_web=False)
        results = [{"url": "https://example.com", "summary": "existing snippet"}]
        await scout._enrich_with_originals(state, results)
        scout.deep_read_url.assert_not_awaited()
        state["search_web"] = True
        await scout._enrich_with_originals(state, results)
        self.assertEqual(results[0]["summary"], "existing snippet")
        self.assertEqual(state["raw_sources"], [])

    async def test_search_cache_hit_skips_remote_api_and_count_is_part_of_key(self):
        scout = DeepScout.__new__(DeepScout)
        scout.logger = logging.getLogger("audit")
        with patch.object(scout_module.search_cache, "get", return_value=[{"title": "cached"}]) as get, \
             patch.object(scout_module.requests, "post") as post:
            result = await scout._execute_search("query", count=6)
        self.assertEqual(result[0]["title"], "cached")
        self.assertEqual(get.call_args.args[0]["count"], 6)
        self.assertEqual(scout_module.search_cache.ttl, 900)
        post.assert_not_called()

    async def test_llm_cache_keys_include_user_account_model_and_generation_settings(self):
        agent = ChiefArchitect("audit-fake-key", "https://example.com/v1", "audit-model")
        agent.cache_scope = "user-one"
        content = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))])
        agent.client = Mock()
        agent.client.chat.completions.create.return_value = content
        stored = {}
        def get(key):
            return stored.get(json.dumps(key, sort_keys=True))
        def put(key, value):
            stored[json.dumps(key, sort_keys=True)] = value
        with patch.object(base_module.llm_cache, "get", side_effect=get), patch.object(base_module.llm_cache, "set", side_effect=put):
            await agent.call_llm("system", "question", temperature=.2, max_tokens=100)
            await agent.call_llm("system", "question", temperature=.2, max_tokens=100)
            self.assertEqual(agent.client.chat.completions.create.call_count, 1)
            agent.cache_scope = "user-two"
            await agent.call_llm("system", "question", temperature=.2, max_tokens=100)
            await agent.call_llm("system", "question", temperature=.3, max_tokens=100)
        self.assertEqual(agent.client.chat.completions.create.call_count, 3)
        self.assertEqual(base_module.llm_cache.ttl, 3600)
        self.assertNotIn("audit-fake-key", str(stored))

    def test_weighted_score_uses_documented_dimensions(self):
        values = {"source_completeness": 9, "logical_rigor": 8, "objectivity": 7,
                  "timeliness": 6, "completeness": 10}
        self.assertEqual(CriticMaster._weighted_score(values), 8.1)
        for invalid in ({}, {**values, "timeliness": float("nan")}, {**values, "timeliness": 11}):
            with self.assertRaises(ValueError):
                CriticMaster._weighted_score(invalid)

    def test_review_prompt_contains_valid_json_example_and_legal_dimension_scores(self):
        prompt = CriticMaster.REVIEW_PROMPT.format(query="audit", outline="", draft_content="",
                                                  facts="", data_points="")
        example = json.loads(prompt.split("```json\n", 1)[1].split("```", 1)[0])
        assessment = example["overall_assessment"]
        self.assertEqual(CriticMaster._weighted_score(assessment["dimension_scores"]), 4.5)
        self.assertNotIn("quality_score", assessment)  # 总分只有程序一个来源
        self.assertIsInstance(example["issues"][0]["requires_new_search"], bool)
        self.assertLess(list(example).index("fact_check_results"), list(example).index("issues"))
        self.assertEqual(list(example)[-1], "overall_assessment")

    async def test_low_weighted_score_cannot_pass_even_when_llm_says_pass(self):
        critic = CriticMaster.__new__(CriticMaster)
        critic.name, critic.logger, critic.add_message = "Critic", logging.getLogger("audit"), Mock()
        critic._review_content = AsyncMock(return_value={"overall_assessment": {"quality_score": 10,
            "verdict": "pass", "dimension_scores": {key: 5 for key in CriticMaster.SCORE_WEIGHTS}}, "issues": []})
        state = create_initial_state("audit", "audit")
        state.update(phase="reviewing", final_report="report")
        await critic.process(state)
        self.assertEqual(state["quality_score"], 5)
        self.assertEqual(state["phase"], "revising")

    async def test_invalid_review_retries_once_with_corrected_prompt(self):
        critic = CriticMaster.__new__(CriticMaster)
        critic.name, critic.logger, critic.add_message = "Critic", logging.getLogger("audit"), Mock()
        dimensions = {key: 8 for key in CriticMaster.SCORE_WEIGHTS}
        invalid = {"overall_assessment": {"dimension_scores": {**dimensions, "source_completeness": 80}}}
        valid = {"overall_assessment": {"dimension_scores": dimensions}, "issues": []}
        critic.call_llm = AsyncMock(side_effect=[json.dumps(invalid), json.dumps(valid)])
        state = create_initial_state("audit", "audit")
        state.update(phase="reviewing", final_report="current report")
        await critic.process(state)
        self.assertEqual(critic.call_llm.await_count, 2)
        prompts = [call.kwargs["user_prompt"] for call in critic.call_llm.call_args_list]
        self.assertNotEqual(prompts[0], prompts[1])
        self.assertIn("本次必须纠正的输出要求", prompts[1])
        self.assertIn("source_completeness=80", prompts[1])
        self.assertIn('"source_completeness": 80', prompts[1])
        self.assertTrue(all(call.kwargs["use_cache"] is False for call in critic.call_llm.call_args_list))
        self.assertEqual(state["quality_score"], 8)
        self.assertEqual(state["quality_review_status"], "confirmed")
        self.assertEqual(state["phase"], "completed")

    async def test_review_retry_provider_failure_preserves_report_without_old_score(self):
        critic = CriticMaster.__new__(CriticMaster)
        critic.name, critic.logger, critic.add_message = "Critic", logging.getLogger("audit"), Mock()
        critic._review_content = AsyncMock(side_effect=[{"overall_assessment": {}}, RuntimeError("provider failure")])
        state = create_initial_state("audit", "audit")
        state.update(phase="reviewing", final_report="revised report", quality_score=8.5,
                     quality_dimensions={key: 8.5 for key in CriticMaster.SCORE_WEIGHTS})
        await critic.process(state)
        self.assertEqual(critic._review_content.await_count, 2)
        self.assertEqual(state["final_report"], "revised report")
        self.assertEqual(state["phase"], "completed")
        self.assertIsNone(state["quality_score"])
        self.assertEqual(state["quality_dimensions"], {})
        self.assertEqual(state["quality_review_status"], "unconfirmed")
        self.assertIn("质量待确认", state["quality_review_note"])

    def test_all_invalid_dimensions_are_reported_without_normalizing_values(self):
        values = {"source_completeness": -1, "logical_rigor": 0,
                  "objectivity": 80, "timeliness": float("nan"), "completeness": None}
        with self.assertRaises(ValueError) as raised:
            CriticMaster._weighted_score(values)
        for key in values:
            self.assertIn(key, str(raised.exception))
        for value in ("=-1", "=0", "=80", "=nan", "NoneType"):
            self.assertIn(value, str(raised.exception))
        self.assertEqual(values["objectivity"], 80)

    async def test_false_fact_without_issue_is_retried_not_approved(self):
        critic = CriticMaster.__new__(CriticMaster)
        critic.name, critic.logger, critic.add_message = "Critic", logging.getLogger("audit"), Mock()
        inconsistent = {"overall_assessment": {"dimension_scores": {key: 10 for key in CriticMaster.SCORE_WEIGHTS}},
                        "fact_check_results": [{"fact_id": "growth", "status": "false", "reason": "计算错误"}], "issues": []}
        corrected = {"overall_assessment": {"dimension_scores": {key: 6 for key in CriticMaster.SCORE_WEIGHTS}},
                     "fact_check_results": inconsistent["fact_check_results"],
                     "issues": [{"issue_type": "logic_error", "severity": "major", "description": "计算错误"}]}
        critic._review_content = AsyncMock(side_effect=[inconsistent, corrected])
        state = create_initial_state("audit", "audit")
        state.update(phase="reviewing", final_report="report", iteration=1, max_iterations=1)
        await critic.process(state)
        self.assertEqual(critic._review_content.await_count, 2)
        self.assertIn("false/suspicious", critic._review_content.call_args.kwargs["score_correction"])
        self.assertEqual(state["quality_score"], 6)
        self.assertEqual(state["unresolved_issues"], 1)

    async def test_critic_valid_dimensions_ignore_model_self_score_and_keep_source_context(self):
        critic = CriticMaster.__new__(CriticMaster)
        critic.name, critic.logger, critic.add_message = "Critic", logging.getLogger("audit"), Mock()
        critic.call_llm = AsyncMock(return_value=json.dumps({
            "overall_assessment": {"quality_score": -1,
                                   "dimension_scores": {key: 8 for key in CriticMaster.SCORE_WEIGHTS}},
            "issues": []}))
        state = create_initial_state("分析用户提供的样本", "audit")
        state.update(phase="reviewing", final_report="用户提供的样本已标注；不外推现实。")
        state["facts"] = [{"id": "f", "content": "样本数据", "source_name": "用户输入",
                           "source_url": "https://example.com/evidence"}]
        await critic.process(state)
        self.assertEqual(state["quality_score"], 8)
        self.assertEqual(state["phase"], "completed")
        critic.call_llm.assert_awaited_once()
        kwargs = critic.call_llm.call_args.kwargs
        self.assertFalse(kwargs["use_cache"])
        self.assertIn("https://example.com/evidence", kwargs["user_prompt"])
        self.assertIn("合成", kwargs["system_prompt"])

    async def test_llm_cache_bypass_neither_reads_nor_writes_and_keeps_default(self):
        agent = ChiefArchitect("audit-fake-key", "https://example.com/v1", "audit-model")
        agent.cache_scope = "audit-user"
        agent.client = Mock()
        agent.client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))])
        with patch.object(base_module.llm_cache, "get", return_value='{"stale":true}') as get, \
             patch.object(base_module.llm_cache, "set") as put:
            self.assertEqual(await agent.call_llm("system", "question", use_cache=False), '{"ok":true}')
            get.assert_not_called()
            put.assert_not_called()
            self.assertEqual(await agent.call_llm("system", "question"), '{"stale":true}')
            get.assert_called_once()
        agent.client.chat.completions.create.assert_called_once()

    async def test_existing_data_points_allow_echarts_generation(self):
        analyst = DataAnalyst.__new__(DataAnalyst)
        analyst.logger = logging.getLogger("audit")
        analyst.call_llm = AsyncMock(return_value='{"charts":[{"title":"Chart","echarts_option":{"series":[]}}]}')
        state = create_initial_state("audit", "audit")
        state["data_points"] = [{"name": "value", "value": 3}]
        charts = await analyst._generate_charts(state, {})
        self.assertEqual(len(charts), 1)
        self.assertTrue(charts[0]["id"])

    async def test_wizard_keeps_multiple_figures(self):
        wizard = CodeWizard.__new__(CodeWizard)
        wizard.logger = logging.getLogger("audit")
        wizard._save_debug_log = Mock()
        wizard._save_debug_info = Mock()
        result = await wizard._execute_code("plt.figure()\nplt.plot([1, 2], [2, 3])\nplt.figure()\nplt.bar([1, 2], [3, 4])")
        self.assertTrue(result["success"])
        self.assertEqual(len(result["charts"]), 2)


class RedisLeaseIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_completion_and_disconnect_release_leases(self):
        token = "audit-" + uuid.uuid4().hex
        lease = ResearchLease(token + "-user", token + "-session")
        closed = []
        async def source():
            try:
                yield "data: first\n\n"
                yield "data: [DONE]\n\n"
            finally:
                closed.append(True)
        try:
            await lease.acquire()
            events = [item async for item in lease.stream(source())]
            self.assertEqual(events, ["data: first\n\n", "data: [DONE]\n\n"])
            self.assertFalse(lease.client.exists(lease.keys[0]))
            lease = ResearchLease(token + "-user", token + "-session")
            await lease.acquire()
            stream = lease.stream(source())
            self.assertEqual(await stream.__anext__(), "data: first\n\n")
            await stream.aclose()
            self.assertFalse(lease.client.exists(lease.keys[0]))
            self.assertEqual(len(closed), 2)
        finally:
            lease.client.delete(*lease.keys)

    async def test_atomic_duplicate_concurrency_limit_release_and_rolling_rate(self):
        token = "audit-" + uuid.uuid4().hex
        user, session = token + "-user", token + "-session"
        first = ResearchLease(user, session)
        keys = set(first.keys)
        try:
            await first.acquire()
            self.assertGreater(first.client.ttl(first.keys[0]), 0)
            duplicate = ResearchLease(user, session)
            keys.update(duplicate.keys)
            with self.assertRaises(HTTPException) as error:
                await duplicate.acquire()
            self.assertEqual(error.exception.status_code, 409)
            await duplicate.release()  # Wrong token must not release the first run.
            self.assertEqual(first.client.get(first.keys[0]), first.token)
            parallel = ResearchLease(user, token + "-other")
            keys.update(parallel.keys)
            with self.assertRaises(HTTPException) as error:
                await parallel.acquire()
            self.assertEqual(error.exception.status_code, 429)
            await first.release()
            for i in range(9):
                lease = ResearchLease(user, session)
                await lease.acquire()
                await lease.release()
            with self.assertRaises(HTTPException) as error:
                await ResearchLease(user, session).acquire()
            self.assertEqual(error.exception.status_code, 429)
            self.assertIn("10", error.exception.detail)
        finally:
            first.client.delete(*keys)

    async def test_redis_failure_fails_closed_before_start(self):
        client = Mock()
        client.eval.side_effect = ConnectionError("offline")
        with self.assertRaises(HTTPException) as error:
            await ResearchLease("audit", "audit", client=client).acquire()
        self.assertEqual(error.exception.status_code, 503)


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main(verbosity=2)
