"""Authenticated ownership for research sessions, including linked legacy records."""
from uuid import UUID
from fastapi import HTTPException

from models.chat import ChatSession
from models.research import ResearchCheckpoint


def authorize_research_session(db, user_id, session_id):
    if not session_id or len(session_id) > 64:
        raise HTTPException(404, "研究会话不存在")
    owner = str(user_id)
    checkpoint = db.query(ResearchCheckpoint).filter(ResearchCheckpoint.session_id == session_id).first()
    try:
        chat_id = UUID(session_id)
    except (ValueError, TypeError):
        chat_id = None
    chat = db.query(ChatSession).filter(ChatSession.id == chat_id).first() if chat_id else None
    if chat is not None and str(chat.user_id) != owner:
        raise HTTPException(404, "研究会话不存在")
    if checkpoint is not None and checkpoint.user_id is not None and str(checkpoint.user_id) != owner:
        raise HTTPException(404, "研究会话不存在")
    if chat is None and (checkpoint is None or str(checkpoint.user_id) != owner):
        raise HTTPException(404, "研究会话不存在")
    if checkpoint is not None and checkpoint.user_id is None:
        checkpoint.user_id = UUID(owner)
        db.commit()
    return checkpoint
