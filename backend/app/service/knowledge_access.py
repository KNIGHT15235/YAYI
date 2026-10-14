"""Authorize access to the existing name-based knowledge collections."""
from uuid import UUID

from fastapi import HTTPException
from models.knowledge import KnowledgeBase
from service.milvus_service import normalize_collection_name


def collection_for_name(name: str) -> str:
    return normalize_collection_name(f"kb_{name}".lower().replace(" ", "_"))


def ensure_collection_is_exclusive(db, kb, name=None):
    collection = collection_for_name(name if name is not None else kb.name)
    others = db.query(KnowledgeBase).filter(KnowledgeBase.id != kb.id).all()
    if any(collection_for_name(other.name) == collection for other in others):
        raise HTTPException(409, "该名称对应的向量集合与其他知识库冲突，请使用唯一名称")


def resolve_owned_knowledge_base(db, user_id, kb_name):
    """Never resolve a user supplied display name directly to a Milvus collection."""
    try:
        owner = UUID(str(user_id))
    except (ValueError, TypeError):
        raise HTTPException(401, "请先登录")
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.user_id == owner, KnowledgeBase.name == kb_name,
    ).first()
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    ensure_collection_is_exclusive(db, kb)
    return kb
