
"""Authenticated research SSE routes with ownership and bounded concurrency."""
import asyncio
import json
import logging
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from core.database import get_db
from core.redis_client import cache
from models.user import User
from router.auth_router import get_current_user_required
from service import ResearchService, ServiceConfig
from service.checkpoint_service import get_checkpoint_service
from service.deep_research_v2.service import DeepResearchV2Service
from service.deep_research_v2.state import create_initial_state
from service.knowledge_access import resolve_owned_knowledge_base
from service.research_access import authorize_research_session
from service.research_guard import ResearchLease
from config.research_profiles import get_research_profile

logger = logging.getLogger("ResearchRouter")
router = APIRouter(prefix="/research", tags=["research"])
CANCEL_KEY_PREFIX = "research:cancel:"
HTTP_200_OK = 200

class ResearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    session_id: Optional[str] = Field(None, min_length=1, max_length=64)
    max_iterations: int = Field(3, ge=1, le=5)
    kb_name: Optional[str] = None
    search_web: Optional[bool] = None
    search_local: Optional[bool] = None
    search_modes: Optional[list[Literal["web", "local"]]] = None
    version: Literal["v1", "v2"] = "v2"
    profile_id: Literal["science", "remote_sensing", "industry"] = "science"
    min_papers: Optional[int] = Field(None, ge=1, le=200)

    def get_search_web(self):
        if self.search_modes is not None:
            return "web" in self.search_modes
        return self.search_web if self.search_web is not None else True

    def get_search_local(self):
        if self.search_modes is not None:
            return "local" in self.search_modes
        return self.search_local if self.search_local is not None else False


class ResumeResearchRequest(BaseModel):
    # Explicit opt-in for completed-but-unresolved research; ordinary resume
    # remains a body-free request. A session can receive at most two extra rounds.
    additional_iterations: Optional[int] = Field(None, ge=1, le=2)
    use_remaining_budget: bool = False
    review_notes: Optional[str] = Field(None, min_length=1, max_length=4000)
    review_claim_ids: Optional[list[str]] = Field(None, max_length=20)


def _prepare_bounded_recheck(full, request):
    """Return an archived, bounded recheck state without changing report verdicts."""
    state = deepcopy(full.get("state_json") or {})
    extra = request.additional_iterations if request else None
    notes = (request.review_notes or "").strip() if request else ""
    review_ids = request.review_claim_ids or [] if request else []
    use_remaining = bool(request and request.use_remaining_budget)
    if use_remaining and (extra is not None or not notes):
        raise HTTPException(422, "使用已授权剩余预算必须提供人工复核意见，且不能同时申请追加轮次")
    if full.get("status") != "completed":
        if extra is not None or notes or review_ids or use_remaining:
            raise HTTPException(400, "追加轮次仅用于已结束且仍有问题的科研任务；中断任务请直接恢复")
        return state, False
    if state.get("research_profile", {}).get("mode") != "science":
        raise HTTPException(400, "已结束任务的追加审核仅支持科研模式")
    claims = state.get("claims") or []
    known_ids = {c.get("claim_id") for c in claims}
    if any(cid not in known_ids for cid in review_ids):
        raise HTTPException(422, "人工复核指定的声明 ID 不存在")
    if review_ids and not notes:
        raise HTTPException(422, "指定复核声明时必须提供 review_notes")
    remaining = (not claims or bool(state.get("unresolved_issues"))
                 or any(c.get("verification_status") != "supported" for c in claims)
                 or state.get("quality_review_status") != "confirmed"
                 or not state.get("evidence_assessment", {}).get("sufficient", False) or bool(notes))
    if not remaining:
        raise HTTPException(400, "研究已完成并通过审核，无需追加轮次")
    if extra is None and not use_remaining:
        raise HTTPException(400, "研究已结束但仍有问题；请显式提供 additional_iterations=1 或 2 追加有限修订审核")
    used = int(state.get("review_extension_rounds", 0))
    remaining_budget = int(state.get("max_iterations", 0)) - int(state.get("iteration", 0))
    if use_remaining and (used <= 0 or remaining_budget <= 0):
        raise HTTPException(400, "没有尚未使用的已授权追加预算")
    extra = extra or 0
    if used + extra > 2:
        raise HTTPException(400, "该研究累计最多追加 2 轮修订审核，已达到追加上限")
    archive = {key: deepcopy(value) for key, value in state.items() if key != "review_history"}
    history = list(state.get("review_history") or [])
    requested_at = datetime.now(timezone.utc).isoformat()
    history.append({"resumed_at": requested_at, "additional_iterations": extra,
                    "used_existing_budget": use_remaining, "remaining_budget_before": remaining_budget,
                    "review_notes": notes, "review_claim_ids": review_ids,
                    "state": archive, "ui_state_json": deepcopy(full.get("ui_state_json") or {})})
    state.update(review_history=history, review_extension_rounds=used + extra,
                 max_iterations=max(int(state.get("max_iterations", 3)), int(state.get("iteration", 0))) + extra,
                 phase="reviewing", _next_step="reviewing")
    if notes:
        state.update(manual_review_request={"notes": notes, "claim_ids": review_ids, "applied": False,
                                            "requested_at": requested_at},
                     phase="revising", _next_step="revising", iteration=int(state.get("iteration", 0)) + 1)
    # Existing claims/scores remain as recorded until the real Critic reruns.
    return state, True

def get_research_service():
    config = ServiceConfig.get_api_config()
    return {"research_service": ResearchService(search_api_key=config.get("bochaai_api_key"),
        llm_api_key=config.get("dashscope_api_key"), llm_base_url=config.get("dashscope_base_url"))}

def get_research_service_v2(max_iterations=None, profile_id="science", min_papers=None):
    return DeepResearchV2Service(max_iterations=max_iterations, profile_id=profile_id, min_papers=min_papers)

def _validate_local(db, user_id, enabled, kb_name):
    if enabled:
        if not kb_name:
            raise HTTPException(422, "本地检索需要选择一个知识库")
        resolve_owned_knowledge_base(db, user_id, kb_name)

def _response(source, lease):
    return StreamingResponse(lease.stream(source), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@router.post("/stream")
async def stream_research(request: ResearchRequest,
        current_user: User = Depends(get_current_user_required), db: Session = Depends(get_db)):
    user_id = str(current_user.id)
    if not request.query.strip():
        raise HTTPException(422, "研究问题不能为空")
    session_id = request.session_id or str(uuid.uuid4())
    if request.session_id:
        authorize_research_session(db, user_id, session_id)
    web, local = request.get_search_web(), request.get_search_local()
    _validate_local(db, user_id, local, request.kb_name)
    lease = await ResearchLease(user_id, session_id).acquire()
    try:
        checkpoints = get_checkpoint_service()
        state = create_initial_state(request.query, session_id, search_web=web, search_local=local)
        state.update(kb_name=request.kb_name, max_iterations=request.max_iterations, version=request.version)
        state.update(profile_id=request.profile_id, research_profile=get_research_profile(request.profile_id, request.min_papers))
        if not checkpoints.save_checkpoint(session_id, state, user_id=user_id, ui_state={}, final_report=""):
            raise HTTPException(503, "检查点保存失败，研究尚未启动")
        if request.version == "v2":
            if request.profile_id == "science" and request.min_papers is None:
                service = get_research_service_v2(request.max_iterations)
            else:
                service = get_research_service_v2(request.max_iterations, request.profile_id, request.min_papers)
            source = service.research(query=request.query, session_id=session_id, user_id=user_id,
                kb_name=request.kb_name, search_web=web, search_local=local)
        else:
            service = get_research_service()["research_service"]
            async def legacy_stream():
                try:
                    yield "data: " + json.dumps({"type": "research_start", "session_id": session_id}) + "\n\n"
                    async for event in service.research_stream(query=request.query,
                            max_iterations=request.max_iterations, kb_name=request.kb_name,
                            search_web=web, search_local=local):
                        if is_research_cancelled(session_id):
                            checkpoints.update_status(session_id, "paused", user_id=user_id)
                            yield 'data: {"type":"research_cancelled"}\n\n'
                            return
                        yield f"data: {event}\n\n"
                    checkpoints.update_status(session_id, "completed", user_id=user_id)
                except (asyncio.CancelledError, GeneratorExit):
                    checkpoints.update_status(session_id, "paused", user_id=user_id)
                    raise
                except Exception:
                    checkpoints.update_status(session_id, "failed", user_id=user_id)
                    raise
            clear_cancel_flag(session_id)
            source = legacy_stream()
        return _response(source, lease)
    except BaseException:
        await lease.release()
        raise

@router.get("/stream")
async def stream_research_get(query: str = Query(..., min_length=1),
        max_iterations: int = Query(3, ge=1, le=5), kb_name: Optional[str] = None,
        search_web: bool = True, search_local: bool = False,
        version: Literal["v1", "v2"] = "v2", session_id: Optional[str] = None,
        profile_id: Literal["science", "remote_sensing", "industry"] = "science",
        min_papers: Optional[int] = Query(None, ge=1, le=200),
        current_user: User = Depends(get_current_user_required), db: Session = Depends(get_db)):
    return await stream_research(ResearchRequest(query=query, max_iterations=max_iterations,
        kb_name=kb_name, search_web=search_web, search_local=search_local,
        version=version, session_id=session_id, profile_id=profile_id, min_papers=min_papers), current_user, db)

@router.post("/cancel/{session_id}")
async def cancel_research(session_id: str, current_user: User = Depends(get_current_user_required),
        db: Session = Depends(get_db)):
    authorize_research_session(db, str(current_user.id), session_id)
    if not cache.set(f"{CANCEL_KEY_PREFIX}{session_id}", {"cancelled": True}, expire=300):
        raise HTTPException(503, "取消请求未保存，请重试")
    return {"success": True, "message": "Research cancellation requested"}

def is_research_cancelled(session_id):
    result = cache.get(f"{CANCEL_KEY_PREFIX}{session_id}")
    return bool(result and result.get("cancelled"))

def clear_cancel_flag(session_id):
    cache.delete(f"{CANCEL_KEY_PREFIX}{session_id}")

@router.get("/checkpoint/{session_id}")
async def get_checkpoint(session_id: str, current_user: User = Depends(get_current_user_required),
        db: Session = Depends(get_db)):
    user_id = str(current_user.id)
    authorize_research_session(db, user_id, session_id)
    info = get_checkpoint_service().get_checkpoint_info(session_id, user_id=user_id)
    return {"success": True, "checkpoint": info} if info else {"success": False, "message": "No checkpoint found"}

@router.get("/checkpoint/{session_id}/full")
async def get_full_checkpoint(session_id: str, current_user: User = Depends(get_current_user_required),
        db: Session = Depends(get_db)):
    user_id = str(current_user.id)
    authorize_research_session(db, user_id, session_id)
    info = get_checkpoint_service().load_full_checkpoint(session_id, user_id=user_id)
    return {"success": True, "checkpoint": info} if info else {"success": False, "message": "No checkpoint found"}

@router.get("/checkpoints")
async def list_checkpoints(status: Optional[str] = Query(None), limit: int = Query(20, ge=1, le=100),
        current_user: User = Depends(get_current_user_required)):
    items = get_checkpoint_service().list_checkpoints(user_id=str(current_user.id), status=status, limit=limit)
    return {"success": True, "checkpoints": items, "total": len(items)}

@router.delete("/checkpoint/{session_id}")
async def delete_checkpoint(session_id: str, current_user: User = Depends(get_current_user_required),
        db: Session = Depends(get_db)):
    user_id = str(current_user.id)
    authorize_research_session(db, user_id, session_id)
    lease = await ResearchLease(user_id, session_id).acquire(count_start=False)
    try:
        success = get_checkpoint_service().delete_checkpoint(session_id, user_id=user_id)
        return {"success": success, "message": "Checkpoint deleted" if success else "Checkpoint not found"}
    finally:
        await lease.release()

@router.post("/resume/{session_id}")
async def resume_research(session_id: str, current_user: User = Depends(get_current_user_required),
        db: Session = Depends(get_db), request: Optional[ResumeResearchRequest] = None):
    user_id = str(current_user.id)
    authorize_research_session(db, user_id, session_id)
    lease = await ResearchLease(user_id, session_id).acquire()
    try:
        # Read under the session lease so two requests cannot reuse a stale
        # extension budget and overwrite each other's review archive.
        checkpoints = get_checkpoint_service()
        full = checkpoints.load_full_checkpoint(session_id, user_id=user_id)
        if not full:
            raise HTTPException(404, "No checkpoint found for this session")
        state = full.get("state_json") or {}
        if state.get("version") == "v1":
            raise HTTPException(400, "旧版研究不支持阶段恢复，请重新开始")
        state, recheck = _prepare_bounded_recheck(full, request)
        _validate_local(db, user_id, state.get("search_local", False), state.get("kb_name"))
        if recheck and not checkpoints.save_checkpoint(session_id, state, user_id=user_id,
                ui_state=full.get("ui_state_json") or {}, final_report=state.get("final_report", "")):
            raise HTTPException(503, "追加审核检查点保存失败，原结果未启动修改")
        service = get_research_service_v2()
        return _response(service.research(query=full.get("query", ""), session_id=session_id,
            resume=True, user_id=user_id), lease)
    except BaseException:
        await lease.release()
        raise

@router.get("/test-wizard", status_code=HTTP_200_OK)
async def test_wizard_endpoint(current_user: User = Depends(get_current_user_required)):
    lease = await ResearchLease(str(current_user.id), "wizard-" + uuid.uuid4().hex).acquire()
    try:
        return await asyncio.wait_for(_test_wizard_impl(), timeout=90)
    finally:
        await lease.release()


async def _test_wizard_impl():
    """
    测试 CodeWizard 数据分析功能（绕过搜索阶段）

    使用模拟数据直接测试图表生成功能。
    """
    from service.deep_research_v2.agents.wizard import CodeWizard
    from service.deep_research_v2.state import ResearchState, ResearchPhase, create_initial_state
    from config.llm_config import get_config

    # 使用配置创建 CodeWizard 实例
    llm_config = get_config()
    wizard = CodeWizard(
        llm_api_key=llm_config.api_key,
        llm_base_url=llm_config.base_url,
        model=llm_config.agents.wizard.model
    )

    # 使用 create_initial_state 创建完整的状态
    mock_state = create_initial_state("中国GDP增长率分析", "test-session")

    # 设置分析阶段
    mock_state["phase"] = ResearchPhase.ANALYZING.value

    # 添加测试大纲
    mock_state["outline"] = [
        {"id": "sec_1", "title": "GDP增长趋势", "requires_chart": True, "section_type": "quantitative", "description": "分析中国近年GDP增长趋势"}
    ]

    # 添加测试数据点
    mock_state["data_points"] = [
        {"name": "2020年GDP增长率", "value": 2.3, "unit": "%"},
        {"name": "2021年GDP增长率", "value": 8.1, "unit": "%"},
        {"name": "2022年GDP增长率", "value": 3.0, "unit": "%"},
        {"name": "2023年GDP增长率", "value": 5.2, "unit": "%"},
        {"name": "2024年GDP增长率", "value": 5.0, "unit": "%"}
    ]

    # 添加测试事实
    mock_state["facts"] = [
        {
            "id": "fact_1",
            "content": "2020年中国GDP增长率为2.3%，是新冠疫情影响下的低谷",
            "source_url": "http://example.com",
            "source_name": "国家统计局",
            "related_sections": ["sec_1"]
        },
        {
            "id": "fact_2",
            "content": "2021年中国GDP强劲反弹，增长率达到8.1%",
            "source_url": "http://example.com",
            "source_name": "国家统计局",
            "related_sections": ["sec_1"]
        }
    ]

    try:
        # 执行数据分析
        result_state = await wizard.process(mock_state)

        charts = result_state.get("charts", [])
        return {
            "success": True,
            "charts_count": len(charts),
            "charts": [
                {
                    "title": c.get("title", ""),
                    "type": c.get("type", ""),
                    "has_image": bool(c.get("image_base64")),
                    "image_length": len(c.get("image_base64", "")) if c.get("image_base64") else 0
                }
                for c in charts
            ],
            "errors": result_state.get("errors", [])
        }
    except Exception as e:
        logger.error(f"Test wizard error: {e}")
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }
