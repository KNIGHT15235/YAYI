"""Per-request research configuration. No mutable global model switching."""
from copy import deepcopy
from .llm_config import resolve_agent_model

PROFILE_VERSION = "2026-10-14.1"
PROFILES = {
    "science": {
        "profile_id": "science", "mode": "science", "discipline": "跨学科科研",
        "version": PROFILE_VERSION, "min_papers": 60, "max_analysis_search_rounds": 2,
        "supplementary_policy": "dual_loop", "max_review_retries": 1,
        "science_retrieval": {"enabled": True, "max_depth": 2, "max_branches": 2,
                              "max_queries": 8, "max_initial_queries": 8, "max_requests": 48, "max_documents": 2400, "max_papers": 200,
                              "max_seconds": 600, "query_timeout_seconds": 90,
                              "proposal_timeout_seconds": 45, "max_batch_queries": 3,
                              "max_batch_requests": 8, "max_batch_documents": 600, "max_batch_seconds": 180,
                              "max_batch_papers": 60},
        "stock_enrichment": False, "allowed_sources": ["literature", "web", "local"],
        "agent_models": {"architect": "deepseek-v3.2", "scout": "qwen-plus",
                         "data_analyst": "qwen-plus", "wizard": "deepseek-v3.2",
                         "writer": "deepseek-v3.2", "critic": "qwen-plus"},
        "method_terms": {
            "Transformer": ["transformer", "vision transformer"],
            "卷积网络": ["convolution", "cnn", "卷积"],
            "孪生网络": ["siamese", "孪生"],
            "注意力机制": ["attention", "注意力"],
            "状态空间模型": ["mamba", "state space model", "状态空间"],
            "自监督/对比学习": ["self-supervised", "contrastive", "自监督", "对比学习"],
            "半监督/弱监督": ["semi-supervised", "weakly supervised", "半监督", "弱监督"],
            "多模态方法": ["multimodal", "multi-modal", "多模态"],
            "扩散模型": ["diffusion model", "diffusion-based", "扩散模型"],
            "基础模型": ["foundation model", "segment anything", "基础模型"],
        },
    },
    "remote_sensing": {
        "profile_id": "remote_sensing", "extends": "science", "discipline": "遥感与地球观测",
        "query_hints": ["remote sensing", "optical imagery", "change detection"],
    },
    "industry": {"profile_id": "industry", "mode": "industry", "discipline": "行业研究",
                 "version": PROFILE_VERSION, "stock_enrichment": True, "agent_models": {}},
}


def get_research_profile(profile_id="science", min_papers=None):
    if profile_id not in PROFILES:
        raise ValueError(f"未知科研配置: {profile_id}")
    profile = deepcopy(PROFILES[profile_id])
    if profile.get("extends"):
        parent = deepcopy(PROFILES[profile.pop("extends")])
        parent.update(profile)
        profile = parent
    if min_papers is not None:
        if not isinstance(min_papers, int) or not 1 <= min_papers <= 200:
            raise ValueError("min_papers 必须在 1 至 200 之间")
        profile["min_papers"] = min_papers
    profile["agent_models"] = {
        name: resolve_agent_model(name, model)
        for name, model in profile.get("agent_models", {}).items()
    }
    return profile
