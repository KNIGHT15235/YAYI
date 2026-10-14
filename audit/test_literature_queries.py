"""Provider query regressions: mocked HTTP only, no research/model requests."""
import copy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "app"))
from service.deep_research_v2 import literature_sources as sources


IDS = ("ev_7886a6bd42fc299b", "claim_e67b6c6cdc1b4ea9", "task_e938ab678c98aabb",
       "asset_" + "a" * 64, "quote_12345678abcdef00",
       "c65524f1-41f5-41d2-8461-0834c922fae7")


class QuerySanitizationTests(unittest.TestCase):
    def test_generated_ids_are_removed_without_damaging_domain_terms(self):
        expected = "hybrid retrieval Recall@20 cross-encoder asset_allocation 10.1234/example 2024"
        self.assertEqual(sources.sanitize_search_query(expected + " " + " ".join(IDS)), expected)
        self.assertEqual(sources.sanitize_search_query(" ".join(IDS)), "")
        self.assertEqual(sources.sanitize_search_query({"reason": "not a query"}), "")

    def test_query_objects_never_turn_diagnostic_reason_into_search_terms(self):
        record = {"search_queries": ["hybrid retrieval recall " + IDS[0]],
                  "query": "fallback ignored", "reason": "DIAGNOSIS_MARKER insufficient ev_12345678"}
        self.assertEqual(sources.provider_search_terms([record]), ["hybrid retrieval recall"])
        self.assertEqual(sources.provider_search_terms([{"reason": record["reason"]}]), [])
        self.assertEqual(sources.provider_search_terms([{"query": "RRF ranking", "reason": record["reason"]}]), ["RRF ranking"])

    def test_empty_or_id_only_focus_falls_back_to_clean_original_scope(self):
        scope = sources.query_scope("2020-2026 hybrid retrieval")
        before = copy.deepcopy(scope)
        self.assertEqual(sources.targeted_searches(scope, list(IDS)), scope["searches"])
        self.assertEqual(sources.targeted_searches(scope, [{"reason": "diagnostic only"}]), scope["searches"])
        self.assertEqual(scope, before)


class ProviderQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_arxiv_filters_ids_from_real_parameter_shape(self):
        response = Mock(content=b'<feed xmlns="http://www.w3.org/2005/Atom"/>')
        client = SimpleNamespace(get=AsyncMock(return_value=response))
        scope = sources.query_scope("2020-2026 hybrid retrieval")
        await sources._arxiv(client, scope, ["recall " + " ".join(IDS)])
        query = client.get.call_args.kwargs["params"]["search_query"]
        self.assertIn('all:"recall"', query)
        self.assertIn("submittedDate:[202001010000", query)
        for value in IDS:
            self.assertNotIn(value, query)
        self.assertEqual(client.get.await_count, 1)

    async def test_arxiv_reason_only_object_uses_original_not_diagnostic(self):
        response = Mock(content=b'<feed xmlns="http://www.w3.org/2005/Atom"/>')
        client = SimpleNamespace(get=AsyncMock(return_value=response))
        await sources._arxiv(client, sources.query_scope("2020-2026 hybrid retrieval"),
                             [{"reason": "DIAGNOSIS_MARKER " + IDS[0]}])
        query = client.get.call_args.kwargs["params"]["search_query"]
        self.assertIn('all:"hybrid"', query)
        self.assertNotIn("diagnosis_marker", query)
        self.assertNotIn(IDS[0], query)

    async def test_crossref_filters_ids_and_never_serializes_reason(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        terms = [{"search_queries": ["recall " + " ".join(IDS)], "reason": "DIAGNOSIS_MARKER"}]
        with tempfile.TemporaryDirectory() as temporary, patch.object(sources, "CACHE_DIR", Path(temporary)), \
             patch.object(sources.httpx, "AsyncClient", return_value=client), \
             patch.object(sources, "_request", new=AsyncMock(return_value=[])) as request, \
             patch.object(sources, "_arxiv", new=AsyncMock(return_value=[])), \
             patch.object(sources.asyncio, "sleep", new=AsyncMock()):
            await sources.collect_literature("2020-2026 hybrid retrieval", min_papers=1, search_terms=terms)
        query = request.call_args.args[1]["query.bibliographic"]
        self.assertIn("hybrid retrieval", query)
        self.assertIn("recall", query)
        self.assertNotIn("DIAGNOSIS_MARKER", query)
        for value in IDS:
            self.assertNotIn(value, query)
        self.assertEqual(request.await_count, 1)


if __name__ == "__main__":
    unittest.main()
