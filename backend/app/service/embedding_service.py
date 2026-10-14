
"""
Embedding 服务 - 使用阿里 DashScope

功能：
1. generate_embedding - 使用 text-embedding-v4 生成向量
2. rerank_similarity - 使用 DashScope Rerank 重排序
"""

import os
from typing import List, Optional, Tuple
import numpy as np
from openai import OpenAI
from llama_index.core.data_structs import Node
from llama_index.core.schema import NodeWithScore
from llama_index.postprocessor.dashscope_rerank import DashScopeRerank

from dotenv import load_dotenv
load_dotenv()


def generate_embedding(
    text: str | List[str],
    api_key: str = None,
    base_url: str = None,
    model_name: str = "text-embedding-v4",
    dimensions: int = 1024,
    encoding_format: str = "float",
    max_batch_size: int = 10
) -> Optional[List[float] | List[List[float]]]:
    """
    生成文本的向量嵌入（使用阿里 text-embedding-v4）

    Args:
        text: 单个文本或文本列表
        api_key: API密钥（默认从环境变量获取）
        base_url: API基础URL（默认从环境变量获取）
        model_name: 模型名称
        dimensions: 向量维度（默认1024）
        encoding_format: 编码格式
        max_batch_size: 最大批量大小（阿里云限制为10）

    Returns:
        单个文本时返回向量，文本列表时返回向量列表
    """
    api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
    base_url = base_url or os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    if not api_key:
        print("错误: 缺少 DASHSCOPE_API_KEY 环境变量")
        return None

    from service.response_cache import RedisJSONCache
    import hashlib
    import math
    cache = RedisJSONCache("embedding-v1", int(os.getenv("EMBEDDING_CACHE_TTL_SECONDS", "86400")))
    single = isinstance(text, str)
    texts = [text] if single else text
    if not isinstance(texts, list):
        return None
    if not texts:
        return []
    credential_scope = hashlib.sha256(api_key.encode()).hexdigest()
    keys = [[base_url, model_name, dimensions, encoding_format, credential_scope, value] for value in texts]
    def valid(vector):
        return (isinstance(vector, list) and len(vector) == dimensions
                and all(isinstance(value, (int, float)) and math.isfinite(value) for value in vector))
    vectors = [cache.get(key) if encoding_format == "float" else None for key in keys]
    missing = {}
    for index, vector in enumerate(vectors):
        if not valid(vector):
            vectors[index] = None
            missing.setdefault(texts[index], []).append(index)
    try:
        if missing:
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=60, max_retries=1)
            pending = list(missing)
            batch_size = max(1, min(int(max_batch_size), 10))
            for offset in range(0, len(pending), batch_size):
                batch = pending[offset:offset + batch_size]
                try:
                    completion = client.embeddings.create(model=model_name, input=batch,
                                                          dimensions=dimensions, encoding_format=encoding_format)
                    for fallback_index, item in enumerate(completion.data):
                        item_index = getattr(item, "index", fallback_index)
                        if not isinstance(item_index, int) or not 0 <= item_index < len(batch):
                            continue
                        vector = item.embedding
                        if encoding_format == "float" and not valid(vector):
                            continue
                        for index in missing[batch[item_index]]:
                            vectors[index] = vector
                        if encoding_format == "float":
                            cache.set(keys[missing[batch[item_index]][0]], vector)
                except Exception as exc:
                    print(f"Embedding request failed ({type(exc).__name__})")
    except Exception as exc:
        print(f"Embedding client failed ({type(exc).__name__})")
    return vectors[0] if single else vectors


def rerank_similarity(
    query: str,
    texts: List[str],
    top_n: int = None
) -> Tuple[np.ndarray, None]:
    """
    使用 DashScope Rerank 对文本进行重排序

    Args:
        query: 查询文本
        texts: 待排序的文本列表
        top_n: 返回前N个结果（默认返回全部）

    Returns:
        (scores, None) - 分数数组和占位符
    """
    api_key = os.getenv("DASHSCOPE_API_KEY")

    if not api_key:
        print("错误: 缺少 DASHSCOPE_API_KEY 环境变量")
        return np.array([]), None

    top_n = top_n or len(texts)

    # 创建节点列表
    nodes = [NodeWithScore(node=Node(text=text), score=1.0) for text in texts]

    # 初始化 DashScopeRerank
    dashscope_rerank = DashScopeRerank(
        model=os.getenv("RERANK_MODEL", "qwen3-rerank"), top_n=top_n, api_key=api_key
    )

    # 执行重排序
    results = dashscope_rerank.postprocess_nodes(nodes, query_str=query)

    # Rerank returns sorted nodes; callers need scores in the original text order.
    by_id = {res.node.node_id: float(res.score) for res in results if res.score is not None}
    scores = np.array([by_id.get(node.node.node_id, float('-inf')) for node in nodes])

    return scores, None
