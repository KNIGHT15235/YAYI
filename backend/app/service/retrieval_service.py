
"""
知识库检索服务 - 基于 Milvus

功能：
1. retrieve_content - 从指定集合检索内容
2. retrieve_from_knowledge_base - 从知识库检索内容
"""

from typing import List, Dict, Any, Optional
import logging
import math
from service.milvus_service import get_milvus_service
from service.embedding_service import generate_embedding, rerank_similarity

logger = logging.getLogger(__name__)


def search_chunks(collection_name, question, top_k=10, kb_id=None, rerank=True):
    """Top-K cosine candidates, optionally reranked; service failures stay explicit."""
    top_k = max(1, min(int(top_k), 50))
    vectors = generate_embedding([question])
    if not vectors or not vectors[0] or len(vectors[0]) != 1024:
        raise ValueError("查询向量生成失败")
    chunks = get_milvus_service().search(collection_name, vectors[0], top_k=top_k, kb_id=kb_id)
    result = {"results": chunks, "reranked": False, "warning": None}
    if not rerank or not chunks:
        return result
    try:
        scores, _ = rerank_similarity(question, [row.get("content", "") for row in chunks])
        if len(scores) != len(chunks) or not all(math.isfinite(float(score)) for score in scores):
            raise ValueError("重排分数缺失")
        result["results"] = sorted(
            [{**row, "rerank_score": float(score)} for row, score in zip(chunks, scores)],
            key=lambda row: row["rerank_score"], reverse=True)
        result["reranked"] = True
    except Exception as exc:
        logger.warning("Rerank unavailable (%s); preserving cosine results", type(exc).__name__)
        result["warning"] = "重排服务暂不可用，已按向量相似度返回结果"
    return result


def retrieve_content(
    indexNames: str,
    question: str,
    top_k: int = 10,
    kb_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    检索相关内容

    Args:
        indexNames: 集合名称（知识库索引）
        question: 查询问题
        top_k: 返回结果数量
        kb_id: 知识库ID（可选过滤）

    Returns:
        检索结果列表
    """
    try:
        results = search_chunks(indexNames, question, top_k, kb_id)["results"]
        from core.database import SessionLocal
        from service.document_assets import enrich_chunks
        with SessionLocal() as db:
            results = enrich_chunks(db, indexNames, results)

        # 3. 格式化结果
        extracted_data = []
        for i, result in enumerate(results, start=1):
            message = {
                "id": i,
                "document_id": result.get("document_id", result.get("doc_id", "N/A")),
                "document_name": result.get("filename", "N/A"),
                "content_with_weight": result.get("content", ""),
                "score": result.get("score", 0),
                "rerank_score": result.get("rerank_score"),
                "chunk_id": result.get("id"),
                "chunk_index": result.get("chunk_index"),
                "document_version": result.get("document_version"),
                "locators": result.get("locators", []),
                "assets": result.get("assets", []),
                "evidence_id": result.get("evidence_id"),
                "content_hash": result.get("content_hash"),
                "download_url": result.get("download_url"),
            }
            extracted_data.append(message)

        return extracted_data

    except Exception as e:
        print(f"检索错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return []


def retrieve_from_knowledge_base(
    kb_name: str,
    question: str,
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    """
    从知识库检索内容

    Args:
        kb_name: 知识库名称
        question: 查询问题
        top_k: 返回结果数量

    Returns:
        检索结果列表
    """
    # 将知识库名称转换为集合名称
    collection_name = f"kb_{kb_name}".lower().replace(" ", "_")
    return retrieve_content(collection_name, question, top_k)
