"""Hybrid recall behavior, cache safety and unchanged downstream contracts."""
import math
import os
from pathlib import Path
import sys
import time
import unittest
from dataclasses import replace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "app"))
from service.bm25_service import (
    BM25Cache, BM25Index, BM25Unavailable, HybridConfig, reciprocal_rank_fusion, tokenize,
)
from service import retrieval_service, milvus_service


def chunk(identity, content="evidence", **kwargs):
    return dict(id=identity, content=content, doc_id="doc-" + identity,
                kb_id="scope", filename="same.pdf", chunk_index=0, **kwargs)


class BM25Tests(unittest.TestCase):
    def build(self, rows, **options):
        return BM25Index(iter(rows), replace(HybridConfig(), **options), time.monotonic() + 30)

    def test_chinese_english_and_scientific_identifiers_share_analyzer(self):
        terms = tokenize("IL-6蛋白质 QWEN-2.5分析 β-catenin DOI 10.1000/ABC")
        for term in ("il-6", "qwen-2.5", "β-catenin", "10.1000/abc", "蛋白质"):
            self.assertIn(term, terms)
        index = self.build([chunk("a", "光学遥感图像变化检测"), chunk("b", "protein growth")])
        self.assertEqual(index.search("遥感图像", 2)[0][0], "a")
        self.assertEqual(index.search("PROTEIN", 2)[0][0], "b")

    def test_formula_positive_idf_and_length_normalization(self):
        index = self.build([chunk("a", "protein protein"), chunk("b", "protein other other other")])
        hits = dict(index.search("protein", 2))
        expected = math.log1p(.5 / 2.5) * 2 * 2.2 / (2 + 1.2 * (.25 + .75 * 2 / 3))
        self.assertAlmostEqual(hits["a"], expected)
        self.assertGreater(hits["a"], hits["b"])
        self.assertGreater(hits["b"], 0)

    def test_no_match_empty_text_and_duplicate_rows(self):
        index = self.build([chunk("a", ""), chunk("b", "protein"), chunk("b", "protein")])
        self.assertEqual(len(index.ids), 2)
        self.assertEqual(index.search("missing", 10), [])
        self.assertEqual(index.search("!!!", 10), [])
        self.assertEqual(self.build([]).search("protein", 10), [])

    def test_repeated_query_terms_do_not_change_scores(self):
        index = self.build([chunk("a", "protein"), chunk("b", "protein extra")])
        self.assertEqual(index.search("protein", 2), index.search("protein protein", 2))

    def test_partial_scan_is_never_used_and_stream_closes(self):
        for options in ({"max_chunks": 1}, {"max_postings": 1}):
            closed = []
            def rows():
                try:
                    yield chunk("a", "first")
                    yield chunk("b", "second")
                finally:
                    closed.append(True)
            with self.assertRaises(BM25Unavailable):
                BM25Index(rows(), replace(HybridConfig(), **options), time.monotonic() + 30)
            self.assertEqual(closed, [True])
        with self.assertRaises(BM25Unavailable):
            BM25Index(iter([chunk("a")]), HybridConfig(), time.monotonic() - 1)

    def test_config_defaults_and_invalid_values_are_bounded(self):
        with patch.dict(os.environ, {"RETRIEVAL_CANDIDATES": "-3", "RETRIEVAL_RRF_K": "bad",
                                    "BM25_K1": "nan", "BM25_B": "4", "RETRIEVAL_HYBRID_ENABLED": "false"}):
            config = HybridConfig.from_env()
        self.assertFalse(config.enabled)
        self.assertEqual((config.candidates, config.rrf_k, config.k1, config.b), (1, 60, 1.2, 1))

    def test_rrf_deduplicates_by_chunk_not_filename_and_preserves_cosine(self):
        dense = [chunk("a", score=.9), chunk("a", score=.9), chunk("b", score=.8)]
        lexical = [chunk("b", bm25_score=2), chunk("c", bm25_score=1)]
        rows = reciprocal_rank_fusion(dense, lexical)
        self.assertEqual([row["id"] for row in rows], ["b", "a", "c"])
        self.assertAlmostEqual(rows[0]["rrf_score"], 1 / 62 + 1 / 61)
        self.assertEqual(rows[0]["score"], .8)
        self.assertEqual(rows[0]["retrieval_sources"], ["vector", "bm25"])
        self.assertIsNone(rows[-1]["score"])


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.cache = BM25Cache()
        self.config = HybridConfig()
        self.loader = MagicMock(side_effect=lambda: iter([chunk("a")]))

    def get(self, collection="kb", scope=None, config=None, loader=None):
        return self.cache.get(collection, scope, loader or self.loader, config or self.config)

    def test_reuse_ttl_lru_and_scope_isolation(self):
        first = self.get()
        self.assertIs(first, self.get())
        self.assertEqual(self.loader.call_count, 1)
        self.assertIsNot(first, self.get(scope="other"))
        self.get(collection="third")
        self.assertIsNot(first, self.get())
        before = self.loader.call_count
        self.get(config=replace(self.config, cache_ttl=0))
        self.assertEqual(self.loader.call_count, before + 1)

    def test_invalidation_and_changed_build_do_not_publish_stale_index(self):
        old = self.get()
        self.cache.invalidate("kb")
        self.assertIsNot(old, self.get())
        self.cache.invalidate("kb")
        def changing():
            yield chunk("a")
            self.cache.invalidate("kb")
        with self.assertRaises(BM25Unavailable):
            self.get(loader=changing)
        self.assertEqual(len(self.cache._entries), 0)
        self.assertIsNotNone(self.get())

    def test_failed_build_does_not_cache_partial_results(self):
        def broken():
            yield chunk("a")
            raise RuntimeError("read failed")
        with self.assertRaises(RuntimeError):
            self.get(loader=broken)
        self.assertEqual(len(self.cache._entries), 0)
        self.assertIsNotNone(self.get())


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.config_patch = patch.object(retrieval_service.HybridConfig, "from_env", return_value=HybridConfig())
        self.config = self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        for name, value in (("generate_embedding", [[.1] * 1024]),
                            ("get_milvus_service", MagicMock()),
                            ("rerank_similarity", None)):
            patcher = patch.object(retrieval_service, name, return_value=value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.service = self.get_milvus_service.return_value
        self.service.search.return_value = [chunk("semantic", "paraphrased evidence", score=.8)]
        self.service.search_keyword.return_value = [chunk("exact", "IL-6 keyword evidence", score=None, bm25_score=4)]
        self.rerank_similarity.side_effect = lambda query, texts: ([.9 if "IL-6" in text else .1 for text in texts], None)

    def test_keyword_only_hit_enters_reranker_and_final_top_k(self):
        result = retrieval_service.search_chunks("kb", "IL-6", top_k=1, kb_id="authorized")
        self.assertEqual(result["results"][0]["id"], "exact")
        self.assertIsNone(result["results"][0]["score"])
        self.assertTrue(result["reranked"])
        self.assertEqual(result["retrieval_method"], "hybrid")
        self.assertEqual(len(self.rerank_similarity.call_args.args[1]), 2)
        for method in (self.service.search, self.service.search_keyword):
            self.assertEqual(method.call_args.kwargs["kb_id"], "authorized")
            self.assertEqual(method.call_args.kwargs["top_k"], 50)

    def test_rerank_disabled_preserves_both_routes_and_final_size(self):
        result = retrieval_service.search_chunks("kb", "IL-6", top_k=2, rerank=False)
        self.assertEqual({row["id"] for row in result["results"]}, {"semantic", "exact"})
        self.rerank_similarity.assert_not_called()

    def test_feature_switch_restores_original_vector_budget(self):
        self.config.return_value = replace(HybridConfig(), enabled=False)
        result = retrieval_service.search_chunks("kb", "IL-6", top_k=3)
        self.assertEqual(result["retrieval_method"], "vector")
        self.assertEqual(self.service.search.call_args.kwargs["top_k"], 3)
        self.service.search_keyword.assert_not_called()
        self.assertEqual(result["results"][0]["score"], .8)

    def test_bm25_failure_and_rerank_failure_preserve_both_warnings(self):
        self.service.search_keyword.side_effect = BM25Unavailable("over budget")
        self.rerank_similarity.side_effect = RuntimeError("unavailable")
        result = retrieval_service.search_chunks("kb", "IL-6")
        self.assertEqual(result["retrieval_method"], "vector")
        self.assertIn("关键词检索", result["warning"])
        self.assertIn("重排服务", result["warning"])
        self.assertEqual(result["results"][0]["score"], .8)

    def test_invalid_rerank_scores_keep_fused_order(self):
        self.rerank_similarity.side_effect = None
        for scores in ([float("nan"), 1], [.9], [float("inf"), .8]):
            self.rerank_similarity.return_value = (scores, None)
            result = retrieval_service.search_chunks("kb", "IL-6", top_k=2)
            self.assertFalse(result["reranked"])
            self.assertIn("混合召回", result["warning"])
            self.assertEqual([row["id"] for row in result["results"]], ["semantic", "exact"])

    def test_expanded_candidates_bounded_before_rerank_and_final_return(self):
        self.service.search.return_value = [chunk(f"d{i}", score=.9) for i in range(50)]
        self.service.search_keyword.return_value = [chunk(f"k{i}", bm25_score=1) for i in range(50)]
        result = retrieval_service.search_chunks("kb", "evidence", top_k=10)
        self.assertEqual(len(self.rerank_similarity.call_args.args[1]), 50)
        self.assertEqual(len(result["results"]), 10)

    def test_missing_embedding_and_dense_failure_remain_explicit(self):
        self.generate_embedding.return_value = [None]
        with self.assertRaises(ValueError):
            retrieval_service.search_chunks("kb", "question")
        self.service.search_keyword.assert_not_called()
        self.generate_embedding.return_value = [[.1] * 1024]
        self.service.search.side_effect = RuntimeError("vector unavailable")
        with self.assertRaises(RuntimeError):
            retrieval_service.search_chunks("kb", "question")

    def test_empty_routes_do_not_call_reranker(self):
        self.service.search.return_value = []
        self.service.search_keyword.return_value = []
        result = retrieval_service.search_chunks("kb", "question")
        self.assertEqual(result["results"], [])
        self.rerank_similarity.assert_not_called()


class MilvusAdapterTests(unittest.TestCase):
    def setUp(self):
        with patch.object(milvus_service.MilvusService, "_connect"):
            self.service = milvus_service.MilvusService()

    def test_iterator_reads_all_batches_closes_and_escapes_scope(self):
        with patch.object(milvus_service.utility, "has_collection", return_value=True), \
                patch.object(milvus_service, "Collection") as collection:
            iterator = collection.return_value.query_iterator.return_value
            iterator.next.side_effect = [[chunk("a")], [chunk("b")], []]
            rows = list(self.service.iter_keyword_chunks("kb_中文", 'scope"quoted'))
            self.assertEqual([row["id"] for row in rows], ["a", "b"])
            args = collection.return_value.query_iterator.call_args.kwargs
            self.assertEqual(args["expr"], 'kb_id == "scope\\"quoted"')
            self.assertEqual(args["consistency_level"], "Strong")
            iterator.close.assert_called_once()

    def test_deleted_cached_ids_are_excluded_and_live_metadata_is_returned(self):
        with patch.object(self.service, "iter_keyword_chunks", return_value=iter([
                chunk("a", "protein"), chunk("b", "protein")])), \
                patch.object(milvus_service.utility, "has_collection", return_value=True), \
                patch.object(milvus_service, "Collection") as collection:
            collection.return_value.query.return_value = [chunk("b", "current protein evidence")]
            rows = self.service.search_keyword("kb", "protein", kb_id="scope")
            self.assertEqual([row["id"] for row in rows], ["b"])
            self.assertEqual(rows[0]["content"], "current protein evidence")
            args = collection.return_value.query.call_args.kwargs
            self.assertIn('and kb_id == "scope"', args["expr"])
            self.assertEqual(args["consistency_level"], "Strong")

    def test_write_delete_rename_and_drop_invalidate_indexes(self):
        with patch.object(self.service._keyword_cache, "invalidate") as invalidate, \
                patch.object(self.service, "create_collection") as create, \
                patch.object(milvus_service.utility, "has_collection", return_value=True), \
                patch.object(milvus_service, "Collection"), \
                patch.object(milvus_service.utility, "drop_collection"):
            self.service.insert_documents("kb", [chunk("a", vector=[.1] * 1024)])
            invalidate.assert_called_with("kb")
            create.return_value.upsert.side_effect = RuntimeError("write status unknown")
            with self.assertRaises(RuntimeError):
                self.service.insert_documents("kb", [chunk("b", vector=[.1] * 1024)])
            self.assertEqual(invalidate.call_count, 2)
            self.service.delete_by_doc_id("kb", "doc-a")
            self.service.delete_collection("kb")
            self.assertEqual(invalidate.call_count, 4)
        with patch.object(self.service._keyword_cache, "invalidate") as invalidate, \
                patch.object(milvus_service.utility, "has_collection", side_effect=[False, True]), \
                patch.object(milvus_service.utility, "rename_collection"):
            self.service.rename_collection("old", "new")
            invalidate.assert_called_once_with("old", "new")


if __name__ == "__main__":
    unittest.main()
