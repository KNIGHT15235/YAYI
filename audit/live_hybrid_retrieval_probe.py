"""Opt-in live Milvus hybrid probe using only UUID-scoped synthetic collections.

Usage: python audit/live_hybrid_retrieval_probe.py --port 29530
No provider calls, real documents or PostgreSQL mutations. Embeddings and rerank
scores are synthetic: this verifies integration, not retrieval quality metrics.
"""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "app"))
os.environ["PYTHON_DOTENV_DISABLED"] = "1"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=29530, type=int)
    parser.add_argument("--database", default="default")
    args = parser.parse_args()
    os.environ.update(MILVUS_HOST=args.host, MILVUS_PORT=str(args.port), MILVUS_DB_NAME=args.database)
    from pymilvus import Collection, utility
    from service.milvus_service import MilvusService
    from service.bm25_service import HybridConfig
    from service import retrieval_service

    service = MilvusService()
    original = "audit_hybrid_" + uuid.uuid4().hex
    renamed = original + "_renamed"
    names = [original, renamed]
    assert all(not utility.has_collection(name) for name in names), "Refuse existing collections"
    results = []

    def check(name, passed):
        results.append({"test": name, "passed": bool(passed)})
        print(json.dumps(results[-1]), flush=True)
        assert passed, name

    vector = [1.0] + [0.0] * 1023
    opposite = [-1.0] + [0.0] * 1023
    scope = 'scope"quoted'
    def row(identity, text, *, kb=scope, vec=vector):
        return {"id": identity, "doc_id": "doc-" + identity, "kb_id": kb, "filename": "same.pdf",
                "content": text, "chunk_index": 0, "vector": vec}
    config = HybridConfig()
    data = [row(f"dense-{i:04}", "Synthetic semantic background") for i in range(300)]
    data += [row("rare", "RAREMARKER-579 exact scientific identifier", vec=opposite),
             row("chinese", "光学遥感图像变化检测", vec=opposite),
             row("other", "RAREMARKER-579 private scope", kb="other", vec=opposite)]
    try:
        service.insert_documents(original, data)
        check("paged full corpus scan", len(list(service.iter_keyword_chunks(original, scope))) == 302)
        dense = service.search(original, vector, top_k=50, kb_id=scope)
        check("synthetic dense top50 misses exact identifier", "rare" not in {r["id"] for r in dense})
        lexical = service.search_keyword(original, "RAREMARKER-579", kb_id=scope)
        check("independent BM25 finds exact identifier and filters scope", [r["id"] for r in lexical] == ["rare"])
        check("Chinese BM25", service.search_keyword(original, "遥感图像", kb_id=scope)[0]["id"] == "chinese")

        with patch.object(retrieval_service, "get_milvus_service", return_value=service), \
                patch.object(retrieval_service, "generate_embedding", return_value=[vector]), \
                patch.object(retrieval_service.HybridConfig, "from_env", return_value=config), \
                patch.object(retrieval_service, "rerank_similarity",
                             side_effect=lambda q, texts: ([.99 if "RAREMARKER-579" in t else .1 for t in texts], None)):
            result = retrieval_service.search_chunks(original, "RAREMARKER-579", top_k=10, kb_id=scope)
            check("hybrid RRF then rerank and final top10", len(result["results"]) == 10
                  and result["results"][0]["id"] == "rare" and result["reranked"] and result["warning"] is None)
            check("cosine metadata preserved", result["results"][0]["score"] is None
                  and any(r["score"] is not None for r in result["results"][1:]))
            with patch.object(retrieval_service.HybridConfig, "from_env", return_value=replace(config, enabled=False)):
                legacy = retrieval_service.search_chunks(original, "RAREMARKER-579", top_k=10, kb_id=scope)
                check("rollback switch uses original vector path", legacy["retrieval_method"] == "vector"
                      and "rare" not in {r["id"] for r in legacy["results"]})
            with patch.object(retrieval_service.HybridConfig, "from_env", return_value=replace(config, max_chunks=1)):
                fallback = retrieval_service.search_chunks(original, "RAREMARKER-579", top_k=10, kb_id=scope)
                check("corpus budget failure visibly falls back", fallback["retrieval_method"] == "vector"
                      and fallback["warning"] and len(fallback["results"]) == 10)

        # Bypass cache invalidation to simulate a write in another worker.
        collection = Collection(original)
        updated = row("rare", "RAREMARKER-579 updated authoritative text", vec=opposite)
        collection.upsert([[updated[field]] for field in ("id", "doc_id", "kb_id", "filename", "content", "chunk_index", "vector")])
        current = service.search_keyword(original, "RAREMARKER-579", kb_id=scope)
        check("warm cache fetches current content", current[0]["content"] == updated["content"])
        collection.delete('doc_id == "doc-rare"')
        check("warm cache never resurrects deleted text", service.search_keyword(original, "RAREMARKER-579", kb_id=scope) == [])
        service.insert_documents(original, [row("new", "NEWMARKER-817 newly uploaded evidence", vec=opposite)])
        check("local upload invalidates keyword cache", service.search_keyword(original, "NEWMARKER-817", kb_id=scope)[0]["id"] == "new")
        service.delete_by_doc_id(original, "doc-new")
        check("local deletion invalidates keyword cache", service.search_keyword(original, "NEWMARKER-817", kb_id=scope) == [])
        service.rename_collection(original, renamed)
        check("rename retains retrieval with existing kb scalar", service.search_keyword(renamed, "遥感图像", kb_id=scope)[0]["id"] == "chinese")
        service.delete_collection(renamed)
        check("drop removes keyword recall", service.search_keyword(renamed, "遥感图像", kb_id=scope) == [])
    finally:
        for name in names:
            if utility.has_collection(name):
                utility.drop_collection(name)
        check("isolated collection cleanup", all(not utility.has_collection(name) for name in names))
    print("LIVE_HYBRID_SUMMARY=" + json.dumps({"server": utility.get_server_version(),
          "checks": len(results), "passed": all(r["passed"] for r in results),
          "embeddings": "synthetic", "rerank": "mocked", "provider_calls": 0}), flush=True)


if __name__ == "__main__":
    main()
