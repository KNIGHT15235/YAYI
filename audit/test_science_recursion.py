"""Offline behavioral tests for scientific retrieval; all provider/LLM calls stubbed."""
import asyncio
import copy
import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "app"))
from service.deep_research_v2 import literature_sources as sources
from service.deep_research_v2 import science_retrieval as retrieval
from service.deep_research_v2.evidence import ensure_science_state, register_evidence, merge_scientific_papers

QUERY = "围绕2020-2026年光学遥感图像变化检测方法开展文献调研，生成文献综述。"


def state(**limits):
    result = {"query": QUERY, "research_profile": {"mode": "science", "min_papers": 1,
               "science_retrieval": {**retrieval.DEFAULT_LIMITS, **limits}},
              "iteration": 0, "search_web": True, "phase": "researching"}
    return ensure_science_state(result)


def paper(i=1, **extra):
    return {"title": f"Optical remote sensing change detection method {i}", "doi": f"10.1234/test{i}",
            "url": f"https://doi.org/10.1234/test{i}", "year": 2024, "verified": True,
            "evidence_level": "abstract", "abstract": "Verified publisher abstract. " * 8,
            "provider": "Crossref", "verification": {"content_level": "publisher_abstract"}, **extra}


def agent():
    return SimpleNamespace(add_message=Mock(), logger=logging.getLogger("recursion-tests"),
                           call_llm=AsyncMock(), parse_json_response=Mock(return_value={"followups": []}))


def crossref(i=1):
    return {"title": [f"Optical remote sensing change detection method {i}"], "DOI": f"10.1234/test{i}",
            "type": "journal-article", "published": {"date-parts": [[2024, 1, 1]]},
            "abstract": "Real fixture abstract. " * 8}


class IdentityTests(unittest.TestCase):
    def test_abstract_upgrade_preserves_id_and_never_downgrades(self):
        s = state()
        merge_scientific_papers(s, [paper(abstract="", content="Long title " * 40, evidence_level="metadata")])
        first = copy.deepcopy(s["papers"][0])
        result = merge_scientific_papers(s, [paper()])
        current = s["papers"][0]
        self.assertEqual(current["evidence_id"], first["evidence_id"])
        self.assertEqual(result["upgraded"], [current["evidence_id"]])
        self.assertEqual(current["evidence_level"], "abstract")
        merge_scientific_papers(s, [paper(abstract="", content="title", evidence_level="metadata",
                                          verification={"content_level": "metadata_only"})])
        self.assertEqual(s["papers"][0]["content"], paper()["abstract"].strip())
        self.assertEqual(s["papers"][0]["verification"]["content_level"], "publisher_abstract")

    def test_arxiv_title_then_doi_keeps_existing_citation(self):
        s = state()
        first = register_evidence(s, paper(doi="", url="https://arxiv.org/abs/2401.12345"))
        upgraded = register_evidence(s, paper(abstract=paper()["abstract"] * 2))
        self.assertEqual(first["source_id"], upgraded["source_id"])
        self.assertEqual(len(s["evidence_ledger"]), 1)
        self.assertEqual(upgraded["doi"], "10.1234/test1")

    def test_corpus_cap_still_allows_existing_paper_upgrades(self):
        s = state()
        merge_scientific_papers(s, [paper(1, abstract="", evidence_level="metadata"), paper(2), paper(3)], max_papers=2)
        self.assertEqual(len(s["papers"]), 2)
        merged = merge_scientific_papers(s, [paper(3), paper(1)], max_papers=2)
        self.assertEqual(len(s["papers"]), 2)
        self.assertEqual(len(merged["upgraded"]), 1)
        self.assertEqual(len(s["evidence_ledger"]), 2)

    def test_generic_original_topic_guards_reject_unrelated_records(self):
        scope = sources.query_scope("2020-2026 quantum error correction literature review")
        self.assertTrue(sources.relevant("Quantum error correction methods", "", scope))
        self.assertFalse(sources.relevant("Transformer building change detection", "", scope))
        chinese = sources.query_scope("2020-2026量子纠错文献综述")
        self.assertTrue(sources.relevant("Quantum error correction", "", chinese))
        self.assertFalse(sources.relevant("Quantum computing hardware", "", chinese))

    def test_focus_does_not_rewrite_original_scope(self):
        scope = sources.query_scope(QUERY)
        queries = sources.targeted_searches(scope, ["cross-scene generalization counterexamples 2012 2030"])
        self.assertEqual(scope["start_year"], 2020)
        self.assertEqual(scope["end_year"], 2026)
        self.assertIn("cross-scene", queries[0])
        self.assertIn("optical remote sensing image change detection", queries[0])
        self.assertNotEqual(queries, scope["searches"])

    def test_shared_focus_key_matches_scout_queue_deduplication(self):
        data = {"original_query": QUERY}
        self.assertIsNone(retrieval.focus_query(data, QUERY))
        self.assertIsNone(retrieval.focus_query(data, None))
        focus = retrieval.focus_query(data, QUERY + "； Cross-scene Generalization!")
        self.assertEqual(retrieval.query_key(focus), "cross scene generalization")
        node = retrieval._node(focus, 0, None)
        self.assertEqual(node["key"], retrieval.query_key("cross scene generalization"))

    def test_legacy_usage_is_explicit_and_existing_counters_preserved(self):
        s = state()
        s["papers"] = [paper()]
        s["analysis_search_round"] = 1
        s["iteration"] = 1
        data = retrieval.ensure_retrieval_state(s)
        self.assertIn("legacy_usage_estimate", data)
        self.assertEqual(data["requests_used"], 21)
        self.assertEqual(data["documents_used"], 2040)
        data["requests_used"] = 23
        self.assertEqual(retrieval.ensure_retrieval_state(s)["requests_used"], 23)
        self.assertEqual(s["analysis_search_round"], 1)
        self.assertEqual(s["iteration"], 1)


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_doi_tracing_resolves_exact_registered_identity(self):
        response = Mock(status_code=200)
        response.json.return_value = {"message": crossref()}
        client = SimpleNamespace(get=AsyncMock(return_value=response))
        result = await sources._request(client, {"query.bibliographic": "optical change detection 10.1234/test1"})
        self.assertEqual(result[0]["DOI"], "10.1234/test1")
        self.assertEqual(client.get.call_args.args[0], "https://api.crossref.org/works/10.1234%2Ftest1")
        self.assertEqual(client.get.call_args.kwargs["params"], {})

    async def test_real_request_attempts_are_counted_even_for_retry(self):
        counters = {}
        budget = sources.RetrievalBudget(counters, {"max_requests": 2, "max_documents": 10})
        response = Mock(status_code=503, headers={})
        client = SimpleNamespace(get=AsyncMock(return_value=response))
        with patch.object(sources.asyncio, "sleep", new=AsyncMock()):
            with self.assertRaises(sources.RetrievalBudgetExhausted):
                await sources._request(client, {}, budget)
        self.assertEqual(client.get.await_count, 2)
        self.assertEqual(counters["requests_used"], 2)

    async def test_focus_reaches_crossref_and_filters_retain_original_years(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        response = Mock()
        response.json.return_value = {"message": {"items": [crossref()]}}
        response.status_code = 200
        client.get.return_value = response
        budget = sources.RetrievalBudget({}, {"max_requests": 10, "max_documents": 100})
        with tempfile.TemporaryDirectory() as tmp, patch.object(sources, "CACHE_DIR", Path(tmp)), \
                patch.object(sources.httpx, "AsyncClient", return_value=client), \
                patch.object(sources, "_arxiv", new=AsyncMock(return_value=[])), \
                patch.object(sources.asyncio, "sleep", new=AsyncMock()):
            rows = await sources.collect_literature(QUERY, 1, original_scope=sources.query_scope(QUERY),
                         search_terms=["cross-scene counterexamples 2012 2030"], budget=budget)
            self.assertEqual(len(rows), 1)
            params = client.get.call_args.kwargs["params"]
            self.assertIn("cross-scene", params["query.bibliographic"])
            self.assertIn("from-pub-date:2020-01-01", params["filter"])
            self.assertNotIn("2030", params["filter"])

    async def test_cache_hits_charge_documents_but_no_http_requests(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        response = Mock(status_code=200)
        response.json.return_value = {"message": {"items": [crossref(1), crossref(2)]}}
        client.get.return_value = response
        with tempfile.TemporaryDirectory() as tmp, patch.object(sources, "CACHE_DIR", Path(tmp)), \
                patch.object(sources.httpx, "AsyncClient", return_value=client), \
                patch.object(sources, "_arxiv", new=AsyncMock(return_value=[])), \
                patch.object(sources.asyncio, "sleep", new=AsyncMock()):
            await sources.collect_literature(QUERY, 1, search_terms=["mechanism"])
            client.get.reset_mock()
            counters = {}
            budget = sources.RetrievalBudget(counters, {"max_requests": 10, "max_documents": 1})
            rows = await sources.collect_literature(QUERY, 1, search_terms=["mechanism"], budget=budget)
            self.assertEqual(len(rows), 1)
            self.assertEqual(counters["documents_used"], 1)
            self.assertEqual(counters.get("requests_used", 0), 0)
            client.get.assert_not_awaited()

    async def test_provider_partial_page_survives_document_budget(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        response = Mock(status_code=200)
        response.json.return_value = {"message": {"items": [crossref(i) for i in range(5)]}}
        client.get.return_value = response
        counters = {}
        budget = sources.RetrievalBudget(counters, {"max_requests": 10, "max_documents": 2})
        sink = Mock()
        with tempfile.TemporaryDirectory() as tmp, patch.object(sources, "CACHE_DIR", Path(tmp)), \
                patch.object(sources.httpx, "AsyncClient", return_value=client), \
                patch.object(sources.asyncio, "sleep", new=AsyncMock()):
            rows = await sources.collect_literature(QUERY, 2, search_terms=["mechanism"], budget=budget, on_papers=sink)
            self.assertEqual(len(rows), 2)
            self.assertEqual(counters, {"requests_used": 1, "documents_used": 2})
            self.assertTrue(sink.called)
            self.assertEqual(list(Path(tmp).glob("*.json")), [])

    async def test_arxiv_focus_enters_provider_query(self):
        client = SimpleNamespace(get=AsyncMock(return_value=Mock(content=b'<feed xmlns="http://www.w3.org/2005/Atom"/>')))
        await sources._arxiv(client, sources.query_scope(QUERY), ["cross-scene generalization counterexamples"])
        query = client.get.call_args.kwargs["params"]["search_query"]
        self.assertIn('all:"generalization"', query)
        self.assertIn("202001010000", query)


class RecursionTests(unittest.IsolatedAsyncioTestCase):
    async def test_malformed_proposal_arrays_finish_node_without_stranded_queue(self):
        for response in ({"followups": None}, {"followups": {}}, {"followups": [None]},
                         {"followups": [{"query": "source tracing", "parent_evidence_ids": None}]},
                         {"followups": [{"query": "source tracing", "parent_evidence_ids": [{"bad": "id"}]}]}):
            with self.subTest(response=response):
                s, a = state(), agent()
                a.parse_json_response.return_value = response
                with patch.object(retrieval, "collect_literature", new=AsyncMock(return_value=[paper()])):
                    await retrieval.collect_scientific_evidence(a, s)
                self.assertEqual(len(s["papers"]), 1)
                self.assertEqual(s["science_retrieval"]["queue"], [])
                self.assertEqual(s["science_retrieval"]["history"][0]["status"], "completed")

    async def test_optional_planner_failure_does_not_block_next_review_query(self):
        s, a = state(), agent()
        with patch.object(retrieval, "collect_literature", new=AsyncMock(return_value=[paper()])) as collect, \
                patch.object(retrieval, "_propose", side_effect=TypeError("invalid proposal")):
            await retrieval.collect_scientific_evidence(a, s)
            self.assertEqual(s["science_retrieval"]["queue"], [])
            self.assertEqual(s["science_retrieval"]["history"][0]["proposal_error"], "TypeError")
            await retrieval.collect_scientific_evidence(a, s, queries=[QUERY + " required mechanism"], supplementary=True)
            self.assertEqual(collect.await_count, 2)
            self.assertEqual(collect.call_args.kwargs["search_terms"], ["required mechanism"])

    async def test_persisted_original_scope_cannot_be_widened_by_later_query(self):
        s, a = state(enabled=False), agent()
        retrieval.ensure_retrieval_state(s)
        s["query"] = "1990-2026 medical imaging review"
        with patch.object(retrieval, "collect_literature", new=AsyncMock(return_value=[paper()])) as collect:
            await retrieval.collect_scientific_evidence(a, s, queries=["uncertainty 1999"], supplementary=True)
            scope = collect.call_args.kwargs["original_scope"]
            self.assertEqual(scope["start_year"], 2020)
            self.assertTrue(scope["optical_change_detection"])
            self.assertEqual(collect.call_args.args[0], QUERY)

    async def test_depth_branch_and_study_query_budgets_survive_new_batches(self):
        s, a = state(max_queries=8, max_depth=2, max_branches=2), agent()
        index = 0
        async def fetch(*args, **kwargs):
            nonlocal index
            index += 1
            kwargs["budget"].charge("request")
            kwargs["budget"].charge("document")
            return [paper(index)]
        async def propose(ag, st, node, ids, limits, timeout):
            return [{"query": f"branch {node['id']} {i}", "evidence_ids": ids, "reason": "trace"} for i in range(2)]
        with patch.object(retrieval, "collect_literature", side_effect=fetch), patch.object(retrieval, "_propose", side_effect=propose):
            await retrieval.collect_scientific_evidence(a, s)
            data = s["science_retrieval"]
            self.assertEqual(data["recursive_queries_used"], 6)
            self.assertEqual(max(n["depth"] for n in data["history"]), 2)
            self.assertEqual(len(s["papers"]), 7)
            await retrieval.collect_scientific_evidence(a, s, queries=["review uncertainty"], supplementary=True)
            self.assertEqual(data["recursive_queries_used"], 8)
            self.assertEqual(data["requests_used"], 10)
            self.assertEqual(len(data["visited"]), len(set(data["visited"])))
            for n in data["history"]:
                self.assertLessEqual(sum(c["parent_id"] == n["id"] for c in data["history"]), 2)

    async def test_no_new_evidence_stops_branch(self):
        s, a = state(), agent()
        async def proposals(*args):
            return [{"query": "same paper", "evidence_ids": [], "reason": "trace"}]
        with patch.object(retrieval, "collect_literature", new=AsyncMock(return_value=[paper()])), \
                patch.object(retrieval, "_propose", side_effect=proposals) as propose:
            await retrieval.collect_scientific_evidence(a, s)
            self.assertEqual(propose.await_count, 1)
            self.assertEqual(s["science_retrieval"]["history"][-1]["status"], "no_new_evidence")
            self.assertEqual(len(s["papers"]), 1)

    async def test_duplicate_followups_are_not_queried_twice(self):
        s, a = state(), agent()
        async def proposals(*args):
            return [{"query": "Same Query!", "evidence_ids": [], "reason": "trace"},
                    {"query": "same query", "evidence_ids": [], "reason": "trace"}]
        with patch.object(retrieval, "collect_literature", new=AsyncMock(return_value=[paper()])) as fetch, \
                patch.object(retrieval, "_propose", side_effect=proposals):
            await retrieval.collect_scientific_evidence(a, s)
            self.assertEqual(fetch.await_count, 2)

    async def test_cancel_preserves_partial_evidence_queue_and_charged_query(self):
        s, a = state(), agent()
        data = retrieval.ensure_retrieval_state(s)
        data["queue"] = [retrieval._node("source tracing", 1, "parent", recursive=True)]
        async def interrupted(*args, **kwargs):
            kwargs["budget"].charge("request")
            kwargs["on_papers"]([paper()])
            raise asyncio.CancelledError()
        with patch.object(retrieval, "collect_literature", side_effect=interrupted):
            with self.assertRaises(asyncio.CancelledError):
                await retrieval.collect_scientific_evidence(a, s)
        self.assertEqual(len(s["papers"]), 1)
        self.assertEqual(data["requests_used"], 1)
        self.assertEqual(data["recursive_queries_used"], 1)
        self.assertEqual(len(data["queue"]), 1)
        # Round-trip exactly like a checkpoint, then retry costs another HTTP call,
        # but never another logical recursive-query allowance.
        s = json.loads(json.dumps(s))
        async def resumed(*args, **kwargs):
            kwargs["budget"].charge("request")
            return [paper()]
        with patch.object(retrieval, "collect_literature", side_effect=resumed):
            await retrieval.collect_scientific_evidence(a, s)
        self.assertEqual(s["science_retrieval"]["requests_used"], 2)
        self.assertEqual(s["science_retrieval"]["recursive_queries_used"], 1)
        self.assertEqual(s["science_retrieval"]["queue"], [])

    async def test_global_request_budget_stops_before_another_query(self):
        s, a = state(max_requests=1), agent()
        async def fetch(*args, **kwargs):
            kwargs["budget"].charge("request")
            return [paper()]
        with patch.object(retrieval, "collect_literature", side_effect=fetch) as mocked:
            await retrieval.collect_scientific_evidence(a, s)
            await retrieval.collect_scientific_evidence(a, s, queries=["new focus"], supplementary=True)
            self.assertEqual(mocked.await_count, 1)
            self.assertEqual(s["science_retrieval"]["stop_reason"], "max_requests")

    async def test_model_proposals_require_real_parent_and_in_scope_years(self):
        s, a = state(), agent()
        retrieval.ensure_retrieval_state(s)
        ev = register_evidence(s, paper())
        a.parse_json_response.return_value = {"followups": [
            {"query": "method 2012", "parent_evidence_ids": [ev["evidence_id"]]},
            {"query": "method 2024", "parent_evidence_ids": ["ev_invented"]},
            {"query": "10.1234/invented", "parent_evidence_ids": [ev["evidence_id"]]},
            {"query": "method limitations", "parent_evidence_ids": [ev["evidence_id"]]}]}
        result = await retrieval._propose(a, s, retrieval._node(None, 0, None), [ev["evidence_id"]], retrieval.DEFAULT_LIMITS, 5)
        self.assertEqual([r["query"] for r in result], ["method limitations"])
        self.assertEqual(len(s["evidence_ledger"]), 1)

    async def test_timeout_keeps_previously_acquired_page_and_ends_branch(self):
        s, a = state(), agent()
        async def timeout(*args, **kwargs):
            kwargs["on_papers"]([paper()])
            raise asyncio.TimeoutError()
        with patch.object(retrieval, "collect_literature", side_effect=timeout):
            await retrieval.collect_scientific_evidence(a, s)
        self.assertEqual(len(s["papers"]), 1)
        self.assertEqual(s["science_retrieval"]["history"][0]["status"], "timeout")
        self.assertEqual(s["science_retrieval"]["queue"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
