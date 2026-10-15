
"""
DeepResearch V2.0 - 可恢复的 asyncio 科研状态机

实现多智能体协作的状态机图：
Plan -> Research -> Analyze -> Write -> Review -> (Revise) -> Complete

线上入口使用 asyncio 状态机和节点内事件队列；保留 LangGraph 定义供历史兼容参考。
"""

import logging
import asyncio
from typing import Dict, Any, List, Literal, AsyncGenerator
from datetime import datetime
from contextlib import aclosing

# 直接使用缓存，避免 router -> service -> graph -> router 的循环导入
# 把取消检查永久替换为无操作函数。
from core.redis_client import cache


def is_research_cancelled(session_id: str) -> bool:
    result = cache.get(f"research:cancel:{session_id}")
    return bool(result and result.get("cancelled"))


def clear_cancel_flag(session_id: str):
    cache.delete(f"research:cancel:{session_id}")

# LangGraph 导入 - 如果没有安装则使用简化版本
try:
    from langgraph.graph import StateGraph, END
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    logging.warning("LangGraph not installed. Using simplified workflow.")

from .state import ResearchState, ResearchPhase, create_initial_state
from .agents import ChiefArchitect, DeepScout, CodeWizard, CriticMaster, LeadWriter, DataAnalyst
from .evidence import ensure_science_state, scientific
from config.research_profiles import get_research_profile

# 导入检查点服务
try:
    from service.checkpoint_service import get_checkpoint_service
except ImportError:
    try:
        from app.service.checkpoint_service import get_checkpoint_service
    except ImportError:
        # 兼容直接运行脚本的情况
        def get_checkpoint_service():
            return None

# 导入配置
try:
    from config.llm_config import get_config, resolve_agent_model
except ImportError:
    try:
        from app.config.llm_config import get_config, resolve_agent_model
    except ImportError:
        # 兼容直接运行脚本的情况
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from config.llm_config import get_config, resolve_agent_model

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("DeepResearchGraph")


class CheckpointPersistenceError(RuntimeError):
    """A transition is not durable, so no downstream phase may start."""


class ResearchEventQueue(asyncio.Queue):
    """Bound UI traffic; only explicitly disposable progress may be removed.

    Critical overflow stops the producer rather than silently losing a result.
    Evidence/report state is persisted by the failure path and can be resumed.
    """
    progress_types = frozenset({"heartbeat", "thought", "thinking", "progress", "literature_progress"})

    def __init__(self, maxsize=256):
        super().__init__(maxsize=maxsize)
        self.dropped_progress = 0
        self.critical_overflow = False

    def put_nowait(self, item):
        if self.full():
            if item.get("type") in self.progress_types:
                self.dropped_progress += 1
                return
            expendable = next((event for event in self._queue if event.get("type") in self.progress_types), None)
            if expendable is None:
                self.critical_overflow = True
                raise asyncio.QueueFull("critical research event buffer exhausted")
            self._queue.remove(expendable)
            self._unfinished_tasks -= 1
            self.dropped_progress += 1
        super().put_nowait(item)


class DeepResearchGraph:
    """
    DeepResearch V2.0 工作流图

    实现完整的多智能体协作流程：
    1. Plan (ChiefArchitect) - 分析问题，生成研究大纲
    2. Research (DeepScout) - 并行深度搜索
    3. Analyze (CodeWizard) - 数据分析和可视化
    4. Write (LeadWriter) - 撰写报告
    5. Review (CriticMaster) - 对抗式审核
    6. Revise (LeadWriter) - 修订（如果需要）
    """

    def __init__(
        self,
        llm_api_key: str = None,
        llm_base_url: str = None,
        search_api_key: str = None,
        model: str = None,
        max_iterations: int = None,
        profile_id: str = "science",
        min_papers: int = None,
    ):
        """
        初始化工作流

        所有参数都可从配置文件读取，传入的参数会覆盖配置
        """
        # 获取配置
        config = get_config()

        # 使用传入参数或配置默认值
        self.llm_api_key = llm_api_key or config.api_key
        self.llm_base_url = llm_base_url or config.base_url
        self.search_api_key = search_api_key or config.search_api_key
        self.model = model or config.default_model
        self.max_iterations = max_iterations or config.research.max_iterations
        self.research_profile = get_research_profile(profile_id, min_papers)

        # 初始化各个 Agent（使用各自配置的模型）
        self.architect = ChiefArchitect(
            self.llm_api_key, self.llm_base_url,
            config.agents.architect.model
        )
        self.scout = DeepScout(
            self.llm_api_key, self.llm_base_url, self.search_api_key,
            config.agents.scout.model
        )
        self.data_analyst = DataAnalyst(
            self.llm_api_key, self.llm_base_url,
            config.agents.data_analyst.model
        )
        self.wizard = CodeWizard(
            self.llm_api_key, self.llm_base_url,
            config.agents.wizard.model
        )
        self.critic = CriticMaster(
            self.llm_api_key, self.llm_base_url,
            config.agents.critic.model
        )
        self.writer = LeadWriter(
            self.llm_api_key, self.llm_base_url,
            config.agents.writer.model
        )
        self._apply_profile_models(self.research_profile)

        logger.info(f"DeepResearchGraph initialized with models:")
        logger.info(f"  - Architect: {self.architect.model}")
        logger.info(f"  - Scout: {self.scout.model}")
        logger.info(f"  - DataAnalyst: {self.data_analyst.model}")
        logger.info(f"  - Wizard: {self.wizard.model}")
        logger.info(f"  - Critic: {self.critic.model}")
        logger.info(f"  - Writer: {self.writer.model}")

        # 检查点服务
        self.checkpoint_service = get_checkpoint_service()

        # 构建图
        if LANGGRAPH_AVAILABLE:
            self.graph = self._build_langgraph()
        else:
            self.graph = None

    def _apply_profile_models(self, profile):
        config = get_config()
        models = profile.setdefault("agent_models", {})
        for name in ("architect", "scout", "data_analyst", "wizard", "writer", "critic"):
            saved = models.get(name)
            model = resolve_agent_model(name, saved or config.get_agent_config(name).model)
            if saved and saved != model:
                logger.info("Explicit model override applied to %s: %s -> %s", name, saved, model)
            agent = getattr(self, name)
            agent.model = model
            agent.model_config = config.get_agent_config(name)
            # Persist the model actually used, including an explicit override on resume.
            models[name] = model

    def _save_checkpoint(
        self,
        state: Dict[str, Any],
        user_id: str = None,
        ui_state: Dict[str, Any] = None
    ) -> bool:
        """保存检查点（包含后端状态和 UI 状态）"""
        if not self.checkpoint_service:
            return False

        session_id = state.get("session_id", "")
        if not session_id:
            return False

        try:
            options = dict(
                session_id=session_id,
                state=state,
                user_id=user_id,
                ui_state=ui_state,
                final_report=state.get("final_report")
            )
            status = state.get("_checkpoint_status", "running")
            error = state.get("_checkpoint_error")
            atomic_status = getattr(self.checkpoint_service, "supports_atomic_status", False) is True
            if atomic_status:
                options.update(status=status, error_message=error)
            checkpoint_id = self.checkpoint_service.save_checkpoint(**options)
            if checkpoint_id:
                # Compatibility for old in-memory adapters; production writes
                # snapshot + status in the same PostgreSQL transaction.
                if not atomic_status and status != "running":
                    if not self.checkpoint_service.update_status(session_id, status, error, user_id=user_id):
                        return False
                logger.info(f"Checkpoint saved: {checkpoint_id}")
                return True
        except Exception as e:
            logger.warning(f"Failed to save checkpoint: {e}")

        return False

    def _load_checkpoint(self, session_id: str, user_id: str = None) -> Dict[str, Any]:
        """加载检查点"""
        if not self.checkpoint_service:
            return None

        try:
            state = self.checkpoint_service.load_checkpoint(session_id, user_id=user_id)
            if state:
                logger.info(f"Checkpoint loaded for session: {session_id}")
                return state
        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {e}")

        return None

    def get_checkpoint_info(self, session_id: str) -> Dict[str, Any]:
        """获取检查点信息"""
        if not self.checkpoint_service:
            return None
        return self.checkpoint_service.get_checkpoint_info(session_id)

    def _build_langgraph(self):
        """构建 LangGraph 状态图"""
        # 定义图
        workflow = StateGraph(ResearchState)

        # 添加节点
        workflow.add_node("plan", self._plan_node)
        workflow.add_node("research", self._research_node)
        workflow.add_node("analyze", self._analyze_node)
        workflow.add_node("write", self._write_node)
        workflow.add_node("review", self._review_node)
        workflow.add_node("revise", self._revise_node)

        # 设置入口
        workflow.set_entry_point("plan")

        # 添加边
        workflow.add_edge("plan", "research")
        workflow.add_edge("research", "analyze")
        workflow.add_edge("analyze", "write")
        workflow.add_edge("write", "review")

        # 条件边：审核后决定下一步
        workflow.add_conditional_edges(
            "review",
            self._should_revise,
            {
                "revise": "revise",
                "complete": END
            }
        )

        # 修订后回到审核
        workflow.add_edge("revise", "review")

        return workflow.compile()

    async def _plan_node(self, state: ResearchState) -> Dict[str, Any]:
        """规划节点"""
        logger.info("Executing Plan node...")
        # 创建状态副本以避免直接修改
        state = dict(state)
        state["phase"] = ResearchPhase.INIT.value
        result = await self.architect.process(state)
        return dict(result)

    async def _research_node(self, state: ResearchState) -> Dict[str, Any]:
        """研究节点"""
        logger.info("Executing Research node...")
        state = dict(state)
        state["phase"] = ResearchPhase.RESEARCHING.value
        result = await self.scout.process(state)
        return dict(result)

    async def _analyze_node(self, state: ResearchState) -> Dict[str, Any]:
        """分析节点"""
        logger.info("Executing Analyze node...")
        state = dict(state)
        state["phase"] = ResearchPhase.ANALYZING.value
        result = await self.wizard.process(state)
        return dict(result)

    async def _write_node(self, state: ResearchState) -> Dict[str, Any]:
        """写作节点"""
        logger.info("Executing Write node...")
        state = dict(state)
        state["phase"] = ResearchPhase.WRITING.value
        result = await self.writer.process(state)
        return dict(result)

    async def _review_node(self, state: ResearchState) -> Dict[str, Any]:
        """审核节点"""
        logger.info("Executing Review node...")
        state = dict(state)
        state["phase"] = ResearchPhase.REVIEWING.value
        result = await self.critic.process(state)
        return dict(result)

    async def _revise_node(self, state: ResearchState) -> Dict[str, Any]:
        """修订节点"""
        logger.info("Executing Revise node...")
        state = dict(state)
        state["phase"] = ResearchPhase.REVISING.value
        result = await self.writer.process(state)
        return dict(result)

    def _should_revise(self, state: ResearchState) -> Literal["revise", "complete"]:
        """决定是否需要修订"""
        # 检查是否有未解决的严重问题
        if state["unresolved_issues"] > 0 and state["iteration"] < state["max_iterations"]:
            return "revise"
        return "complete"

    async def run(
        self,
        query: str,
        session_id: str,
        resume: bool = False,
        user_id: str = None,
        search_web: bool = True,
        search_local: bool = False,
        kb_name: str = None,
        knowledge_base_id: str = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        执行研究流程（流式输出）

        Args:
            query: 用户问题
            session_id: 会话ID
            resume: 是否从检查点恢复
            user_id: 用户ID（用于检查点）
            search_web: 是否启用网络搜索（默认True）
            search_local: 是否启用本地知识库搜索（默认False）

        Yields:
            SSE 事件字典
        """
        # 尝试从检查点恢复
        state = None
        if resume and session_id:
            state = self._load_checkpoint(session_id, user_id=user_id)
            if not state:
                yield {"type": "error", "code": "checkpoint_load_failed",
                       "content": "检查点未能读取，未重置或重新启动研究；请稍后重试。"}
                return
            if state:
                yield {
                    "type": "research_resumed",
                    "phase": state.get("phase", ""),
                    "session_id": session_id,
                    "timestamp": datetime.now().isoformat()
                }

        # 如果没有检查点，创建初始状态
        if not state:
            state = create_initial_state(
                query, session_id,
                search_web=search_web,
                search_local=search_local
            )
            state["max_iterations"] = self.max_iterations
            state["kb_name"] = kb_name
            state["knowledge_base_id"] = knowledge_base_id
            state["research_profile"] = getattr(self, "research_profile", get_research_profile("industry"))
            state["profile_id"] = state["research_profile"]["profile_id"]

            yield {
                "type": "research_start",
                "query": query,
                "session_id": session_id,
                "search_web": search_web,
                "search_local": search_local,
                "timestamp": datetime.now().isoformat()
            }

        # Keep saved models on resume unless an operator explicitly overrides them.
        if "research_profile" not in state:
            state["research_profile"] = get_research_profile("industry") if resume else getattr(self, "research_profile", get_research_profile("industry"))
        self._apply_profile_models(state["research_profile"])
        if scientific(state):
            ensure_science_state(state)
            from .science_roles import migrate_science_policy
            migrate_science_policy(state)

        # 存储 user_id 用于检查点
        state["_user_id"] = user_id
        for agent in (self.architect, self.scout, self.data_analyst, self.wizard, self.writer, self.critic):
            agent.cache_scope = str(user_id) if user_id else None

        # 当前产品选择 asyncio 执行器以集中管理节点内进度、取消与恢复。
        # 这是本项目的实现选择，并非 LangGraph 不支持实时流式输出。
        async with aclosing(self._run_simplified(state)) as events:
            async for event in events:
                yield event

    async def _run_with_langgraph(self, state: ResearchState) -> AsyncGenerator[Dict[str, Any], None]:
        """使用 LangGraph 执行"""
        # 追踪已输出的消息数量，避免重复
        yielded_count = 0

        try:
            # LangGraph 的流式执行
            async for output in self.graph.astream(state):
                # 提取消息并输出
                for node_name, node_state in output.items():
                    if isinstance(node_state, dict) and "messages" in node_state:
                        messages = node_state["messages"]
                        # 只输出新消息（跳过已输出的）
                        new_messages = messages[yielded_count:]
                        for message in new_messages:
                            yield message
                        yielded_count = len(messages)

        except Exception as e:
            logger.error(f"LangGraph execution error: {e}")
            yield {"type": "error", "content": str(e)}

    async def _run_simplified(self, state: ResearchState) -> AsyncGenerator[Dict[str, Any], None]:
        """
        简化版执行流程（不依赖 LangGraph）

        使用 asyncio.Queue 实现实时流式输出
        """
        # 创建消息队列用于实时输出
        message_queue = ResearchEventQueue()
        state["_message_queue"] = message_queue
        active_task = None
        active_monitor = None
        terminal_persisted = False

        # 获取 session_id 用于取消检查
        session_id = state.get("session_id", "")

        # The authenticated router clears the old flag before returning SSE.
        # Clearing here would erase a cancellation sent after research_start.

        class ResearchCancelled(Exception):
            """User cancellation exits the phase before normal completion checks."""

        async def check_cancelled():
            """检查是否已取消"""
            if session_id and is_research_cancelled(session_id):
                return True
            return False

        async def run_agent_with_streaming(agent):
            """执行 agent 并实时 yield 消息"""
            nonlocal active_task, active_monitor
            # 检查是否已取消
            if await check_cancelled():
                logger.info(f"Research cancelled before starting agent: {agent.name}")
                raise ResearchCancelled()

            logger.info(f"Starting agent: {agent.name}")

            # 启动 agent 处理任务
            task = asyncio.create_task(agent.process(state))
            active_task = task
            cancelled = asyncio.Event()

            async def monitor_cancellation():
                # Runs even while the SSE generator is suspended on a slow
                # consumer. Cancellation must not wait for another socket read.
                while not task.done():
                    if await check_cancelled():
                        cancelled.set()
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                        try:
                            await save_checkpoint_async({"type": state.get("phase"), "status": "paused"},
                                                        next_step=state.get("_next_step"), status="paused")
                        except Exception:
                            logger.exception("Cancellation snapshot was not persisted")
                        return
                    await asyncio.sleep(0.2)

            cancellation_monitor = asyncio.create_task(monitor_cancellation())
            active_monitor = cancellation_monitor

            msg_count = 0
            last_event = asyncio.get_running_loop().time()
            # 在任务执行期间持续从队列获取消息
            while not task.done():
                # 定期检查是否已取消
                if await check_cancelled():
                    logger.info(f"Research cancelled during agent: {agent.name}")
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    cancellation_monitor.cancel()
                    await asyncio.gather(cancellation_monitor, return_exceptions=True)
                    raise ResearchCancelled()

                try:
                    msg = await asyncio.wait_for(message_queue.get(), timeout=0.5)
                    msg_count += 1
                    msg_type = msg.get('type', 'unknown')
                    logger.info(f"[SSE YIELD] [{agent.name}] #{msg_count}: {msg_type}")
                    last_event = asyncio.get_running_loop().time()
                    yield msg
                except asyncio.TimeoutError:
                    if asyncio.get_running_loop().time() - last_event >= 15:
                        yield {"type": "heartbeat", "session_id": session_id}
                        last_event = asyncio.get_running_loop().time()
                    continue
                except (asyncio.CancelledError, GeneratorExit):
                    task.cancel()
                    cancellation_monitor.cancel()
                    await asyncio.gather(task, cancellation_monitor, return_exceptions=True)
                    raise
                except Exception as e:
                    logger.warning(f"[{agent.name}] Queue error: {e}")
                    continue

            cancellation_monitor.cancel()
            await asyncio.gather(cancellation_monitor, return_exceptions=True)
            if cancelled.is_set():
                raise ResearchCancelled()
            if message_queue.critical_overflow:
                await asyncio.gather(task, return_exceptions=True)
                raise RuntimeError("研究关键事件缓冲区已满，已停止当前阶段；请恢复研究")
            # 等待任务完成（获取可能的异常）
            try:
                await task
            except Exception as e:
                logger.error(f"Agent {agent.name} error: {e}")
                raise

            # 清空剩余的消息
            remaining = 0
            while not message_queue.empty():
                try:
                    msg = message_queue.get_nowait()
                    remaining += 1
                    yield msg
                except asyncio.QueueEmpty:
                    break

            logger.info(f"Agent {agent.name} completed. Messages: {msg_count} during, {remaining} remaining")

        # 获取 user_id 用于检查点
        user_id = state.get("_user_id")

        # UI 状态跟踪（用于前端恢复）
        ui_state = {
            "research_steps": [],  # 研究步骤列表
            "search_results": [],  # 搜索结果
            "charts": [],  # 图表数据
            "knowledge_graph": None,  # 知识图谱
            "streaming_report": "",  # 流式报告内容
        }
        if self.checkpoint_service and state.get("_next_step"):
            checkpoint = self.checkpoint_service.load_full_checkpoint(session_id, user_id=user_id)
            if checkpoint and checkpoint.get("ui_state_json"):
                ui_state.update(checkpoint["ui_state_json"])

        def update_ui_state():
            """更新 UI 状态 - 保留已有数据，只有新数据才更新"""
            # 从 state 中同步数据到 ui_state - 只有当新数据有效时才更新
            new_charts = state.get("charts", [])
            if new_charts:
                ui_state["charts"] = new_charts

            new_report = state.get("final_report", "")
            if new_report:
                ui_state["streaming_report"] = new_report

            # 知识图谱 - 只有当有节点或边时才更新
            new_kg = state.get("knowledge_graph", {})
            if new_kg and (new_kg.get("nodes") or new_kg.get("edges")):
                ui_state["knowledge_graph"] = new_kg
            elif not ui_state.get("knowledge_graph"):
                ui_state["knowledge_graph"] = {"nodes": [], "edges": []}

            # 提取搜索结果 - 从 facts 中构建 UI 友好的搜索结果
            facts = state.get("facts", [])
            if facts:
                search_results_for_ui = []
                for fact in facts:
                    # 优先使用 source_name，否则从 content 中提取标题
                    source_name = fact.get("source_name", "")
                    content = fact.get("content", "")
                    # 如果没有 source_name，用 content 的前50个字符作为标题
                    title = source_name if source_name else (content[:50] + "..." if len(content) > 50 else content)
                    search_results_for_ui.append({
                        "id": fact.get("id", ""),
                        "title": title,
                        "source": fact.get("source_type", "web"),
                        "url": fact.get("source_url", ""),
                        "snippet": content[:200] if content else "",
                        "date": fact.get("timestamp", ""),
                    })
                ui_state["search_results"] = search_results_for_ui

            # 构建前端友好的 references - 确保有 title 和 link 字段
            raw_references = state.get("references", [])
            ui_references = []
            for idx, ref in enumerate(raw_references):
                # 从 facts 中查找对应的详细信息
                fact = next((f for f in facts if f.get("source_url") == ref.get("url")), None)
                # 确定标题：优先用 source/marker，否则用 fact 的内容
                title = ref.get("source") or ref.get("marker") or ""
                if not title and fact:
                    content = fact.get("content", "")
                    title = content[:50] + "..." if len(content) > 50 else content
                if not title:
                    title = f"来源 {idx + 1}"

                ui_references.append({
                    **ref,
                    "id": ref.get("id", idx + 1),
                    "title": title,
                    "link": ref.get("url", ""),
                    "content": fact.get("content", "")[:200] if fact else "",
                    "source": "web"
                })
            ui_state["references"] = ui_references
            for key in ("papers", "evidence_ledger", "claims", "claim_verification", "evidence_assessment",
                        "hypotheses", "corpus_statistics", "research_profile", "profile_id", "literature_errors"):
                if key in state:
                    ui_state[key] = state[key]

            # 打印详细日志
            kg = ui_state.get("knowledge_graph", {})
            logger.info(f"[UI状态更新] charts={len(ui_state.get('charts', []))}, "
                       f"search_results={len(ui_state.get('search_results', []))}, "
                       f"knowledge_graph nodes={len(kg.get('nodes', []) if kg else [])}, "
                       f"knowledge_graph edges={len(kg.get('edges', []) if kg else [])}, "
                       f"references={len(ui_state.get('references', []))}, "
                       f"report_len={len(ui_state.get('streaming_report', ''))}")

        async def save_checkpoint_async(step_info: dict = None, next_step: str = None,
                                        status: str = "running", error_message: str = None):
            """异步保存检查点"""
            if next_step:
                state["_next_step"] = next_step
            # 更新 UI 状态
            update_ui_state()
            # 添加研究步骤
            if step_info:
                # 检查是否已有该步骤，更新状态
                existing = next(
                    (s for s in ui_state["research_steps"] if s.get("type") == step_info.get("type")),
                    None
                )
                if existing:
                    existing.update(step_info)
                    logger.info(f"[检查点] 更新步骤: {step_info.get('type')}, status={step_info.get('status')}")
                else:
                    ui_state["research_steps"].append(step_info)
                    logger.info(f"[检查点] 添加步骤: {step_info.get('type')}, status={step_info.get('status')}")

            # 打印保存前的完整状态
            logger.info(f"[检查点保存] session_id={session_id}, phase={state.get('phase', '')}, "
                       f"steps={[s.get('type') for s in ui_state['research_steps']]}")

            state["_checkpoint_status"] = status
            state["_checkpoint_error"] = error_message
            if self._save_checkpoint(state, user_id, ui_state):
                logger.info(f"[检查点保存成功] session_id={session_id}")
                return {"type": "checkpoint_saved", "phase": state.get("phase", ""), "session_id": session_id}
            raise CheckpointPersistenceError("检查点持久化失败；研究已停止，当前阶段未确认保存。只能从最后成功的检查点恢复。")

        try:
            if scientific(state):
                from .science_roles import migrate_science_policy
                migrate_science_policy(state)
            # 保存下一待执行步骤，使恢复只重做未完成阶段；兼容旧检查点。
            legacy_next = {"init": "planning", "planning": "researching",
                           "researching": "analyzing", "analyzing": "writing"}
            next_step = state.get("_next_step") or legacy_next.get(
                state.get("phase"), state.get("phase", "planning"))
            if not state.get("_next_step"):
                await save_checkpoint_async(next_step=next_step)
            # One explicit phase loop supports both analysis and review search returns.
            # Save next_step before/after each phase so an interruption only repeats
            # its unfinished phase; an Analyst redirect must skip Wizard/Writer.
            while next_step != "completed":
                if await check_cancelled():
                    raise ResearchCancelled()
                step = next_step
                state["phase"] = "init" if step == "planning" else step
                yield {"type": "phase", "phase": next_step, "content": f"执行 {next_step}..."}
                if step == "planning":
                    async for msg in run_agent_with_streaming(self.architect):
                        yield msg
                    next_step = "researching"
                elif step == "researching":
                    async for msg in run_agent_with_streaming(self.scout):
                        yield msg
                    next_step = "analyzing"
                elif step == "analyzing":
                    async for msg in run_agent_with_streaming(self.data_analyst):
                        yield msg
                    if scientific(state) and state.get("phase") in {"reviewing", "completed"}:
                        next_step = state["phase"]
                    elif state.get("phase") == "re_researching":
                        next_step = "re_researching"
                    else:
                        async for msg in run_agent_with_streaming(self.wizard):
                            yield msg
                        next_step = state.pop("analysis_continuation", "writing") if scientific(state) else "writing"
                elif step == "writing":
                    async for msg in run_agent_with_streaming(self.writer):
                        yield msg
                    next_step = "reviewing"
                elif next_step in {"reviewing", "review_retry"}:
                    prior_retry = state.get("review_retry_count", 0)
                    async for msg in run_agent_with_streaming(self.critic):
                        yield msg
                    next_step = state["phase"]
                    if next_step == "reviewing":
                        raise RuntimeError("审核未返回有效结论，研究未完成")
                    if step == "review_retry" and next_step == "review_retry" and state.get("review_retry_count", 0) <= prior_retry:
                        raise RuntimeError("审核重试未消耗有限预算，已停止无进展循环")
                elif next_step == "re_researching":
                    async for msg in run_agent_with_streaming(self.scout):
                        yield msg
                    # Every scientific supplement re-evaluates hypotheses and coverage
                    # before updating figures and revising the existing claims.
                    if scientific(state):
                        state.setdefault("analysis_continuation", "revising" if state.get("claims") else "writing")
                        next_step = "analyzing"
                    else:
                        next_step = state.get("return_phase") or "revising"
                elif next_step == "revising":
                    async for msg in run_agent_with_streaming(self.writer):
                        yield msg
                    next_step = "reviewing"
                else:
                    raise RuntimeError(f"未知研究恢复阶段: {next_step}")
                # A phase may finish just as cancellation is requested. Persist
                # its continuation (including revising after Analyze), not its
                # consumed work as if it had never happened.
                state["_next_step"] = next_step
                if await check_cancelled():
                    raise ResearchCancelled()
                state["messages"] = []
                # A graceful workflow stop can still mean this node failed.
                # Preserve that distinction in the durable timeline instead of
                # turning a provider/schema failure into a green completed step.
                phase_unavailable = next_step == "completed" and (
                    (step == "analyzing" and state.get("stop_reason") == "analysis_unavailable")
                    or (step in {"reviewing", "review_retry"} and state.get("stop_reason") == "review_unavailable")
                )
                step_info = {
                    "type": step, "status": "failed" if phase_unavailable else "completed",
                    "subtitle": state.get("quality_review_note", "") if phase_unavailable else "",
                    "stats": {"sections": len(state.get("outline", [])), "facts": len(state.get("facts", [])),
                              "charts": len(state.get("charts", [])), "report_length": len(state.get("final_report", ""))}
                } if scientific(state) or step in {"planning", "researching", "analyzing", "writing"} else None
                cp_event = await save_checkpoint_async(step_info, next_step=next_step)
                if cp_event:
                    yield cp_event

            # 完成
            logger.info(f"[Graph] ========== 研究完成 ==========")
            logger.info(f"[Graph] 最终统计: facts={len(state.get('facts', []))}, charts={len(state.get('charts', []))}, iterations={state.get('iteration', 0)}")
            logger.info(f"[Graph] 报告长度: {len(state.get('final_report', ''))}")

            # 打印每个图表的详情
            for i, chart in enumerate(state.get('charts', [])):
                logger.info(f"[Graph] 图表 {i+1}: id={chart.get('id')}, title={chart.get('title')}, has_echarts={bool(chart.get('echarts_option'))}, has_image={bool(chart.get('image_base64'))}")

            # 更新检查点状态为已完成
            state["phase"] = ResearchPhase.COMPLETED.value
            if not state.get("final_report", "").strip():
                raise RuntimeError("研究未生成报告，不能标记为完成")
            await save_checkpoint_async(next_step="completed", status="completed")
            terminal_persisted = True

            # 构建前端友好的 references
            final_facts = state.get("facts", [])
            final_raw_refs = state.get("references", [])
            final_ui_refs = []
            for idx, ref in enumerate(final_raw_refs):
                fact = next((f for f in final_facts if f.get("source_url") == ref.get("url")), None)
                title = ref.get("source") or ref.get("marker") or ""
                if not title and fact:
                    content = fact.get("content", "")
                    title = content[:50] + "..." if len(content) > 50 else content
                if not title:
                    title = f"来源 {idx + 1}"
                final_ui_refs.append({
                    **ref,
                    "id": ref.get("id", idx + 1),
                    "title": title,
                    "link": ref.get("url", ""),
                    "content": fact.get("content", "")[:200] if fact else "",
                    "source": "web"
                })

            yield {
                "type": "research_complete",
                "outcome": state.get("outcome", "completed_with_warnings"),
                "research_outcome": state.get("outcome", "completed_with_warnings"),
                "review_verdict": state.get("review_verdict", "unconfirmed"),
                "stop_reason": state.get("stop_reason", "legacy_completion"),
                "dropped_progress_events": message_queue.dropped_progress,
                "final_report": state.get("final_report", ""),
                "quality_score": state.get("quality_score", 0.0),
                "facts_count": len(state.get("facts", [])),
                "charts_count": len(state.get("charts", [])),
                "iterations": state.get("iteration", 0),
                "references": final_ui_refs,
                "charts": state.get("charts", []),
                "knowledge_graph": state.get("knowledge_graph", {}),
                "papers": state.get("papers", []),
                "evidence_ledger": state.get("evidence_ledger", {}),
                "claims": state.get("claims", []),
                "claim_verification": state.get("claim_verification", {}),
                "evidence_assessment": state.get("evidence_assessment", {}),
                "hypotheses": state.get("hypotheses", []),
                "corpus_statistics": state.get("corpus_statistics", {}),
                "profile_id": state.get("profile_id"),
                "quality_dimensions": state.get("quality_dimensions", {}),
                "quality_review_status": state.get("quality_review_status", "unconfirmed"),
                "quality_review_note": state.get("quality_review_note", "")
            }

        except CheckpointPersistenceError as error:
            yield {"type": "error", "code": "checkpoint_persistence_failed", "content": str(error),
                   "recoverable": False, "last_checkpoint_only": True, "checkpoint_saved": False}
        except ResearchCancelled:
            # Keep partial results and rerun this unfinished phase on resume.
            # In particular, a cancelled Critic has no verdict by design; it
            # must never fall through to the "missing review" failure path.
            try:
                await save_checkpoint_async({"type": state.get("phase"), "status": "paused"},
                                            next_step=state.get("_next_step") or state.get("phase"), status="paused")
            except CheckpointPersistenceError as error:
                yield {"type": "error", "code": "checkpoint_persistence_failed", "content": str(error),
                       "recoverable": False, "last_checkpoint_only": True, "checkpoint_saved": False}
            else:
                yield {"type": "research_cancelled", "message": "研究已取消，已保存检查点", "session_id": session_id,
                       "checkpoint_saved": True}
        except (asyncio.CancelledError, GeneratorExit):
            if terminal_persisted:
                # Closing the SSE response after receiving research_complete
                # must not downgrade a durable completion into "paused".
                raise
            if active_task and not active_task.done():
                active_task.cancel()
                await asyncio.gather(active_task, return_exceptions=True)
            # Persist in-flight retrieval counters and partial verified evidence,
            # including cancellation by SSE disconnect rather than the cancel API.
            try:
                await save_checkpoint_async({"type": state.get("phase"), "status": "paused"},
                                            next_step=state.get("_next_step") or state.get("phase"), status="paused")
            except Exception:
                logger.exception("Disconnected research stopped but its latest snapshot was NOT saved")
            raise
        except Exception as e:
            logger.error(f"Simplified execution error: {e}")
            # Keep evidence acquired inside the failed phase, not just the last
            # completed phase. Resume retries its saved continuation normally.
            try:
                await save_checkpoint_async({"type": state.get("phase"), "status": "failed"},
                                            next_step=state.get("_next_step") or state.get("phase"), status="failed", error_message=str(e))
            except Exception as checkpoint_error:
                # A secondary display/storage failure must not hide the cause
                # of the research failure or turn it into a completion event.
                logger.error(f"Failed to prepare partial research snapshot: {checkpoint_error}")
                state.update(_checkpoint_status="failed", _checkpoint_error=str(e))
                if not self._save_checkpoint(state, user_id, ui_state):
                    yield {"type": "error", "code": "checkpoint_persistence_failed", "content": str(e),
                           "checkpoint_error": str(checkpoint_error), "checkpoint_saved": False,
                           "recoverable": False, "last_checkpoint_only": True}
                    return
            yield {"type": "error", "content": str(e)}
        finally:
            if active_task and not active_task.done():
                active_task.cancel()
                await asyncio.gather(active_task, return_exceptions=True)
            if active_monitor:
                active_monitor.cancel()
                await asyncio.gather(active_monitor, return_exceptions=True)
            # 清理队列
            state["_message_queue"] = None

    async def run_sync(self, query: str, session_id: str) -> ResearchState:
        """
        同步执行（返回最终状态）

        用于不需要流式输出的场景
        """
        state = create_initial_state(query, session_id)
        state["max_iterations"] = self.max_iterations
        state["research_profile"] = getattr(self, "research_profile", get_research_profile("industry"))
        state["profile_id"] = state["research_profile"]["profile_id"]
        if scientific(state):
            ensure_science_state(state)

        # 与流式入口复用阶段切换；直接依次调用 process 会使 Analyst/Writer
        # 因为 phase 仍为 researching 而跳过执行。
        async for event in self._run_simplified(state):
            if event.get("type") == "error":
                raise RuntimeError(event.get("content", "Research failed"))

        return state


def create_research_graph(
    llm_api_key: str = None,
    llm_base_url: str = None,
    search_api_key: str = None,
    model: str = None
) -> DeepResearchGraph:
    """
    工厂函数：创建 DeepResearch 工作流图

    所有参数都是可选的，会从配置文件读取默认值

    Args:
        llm_api_key: LLM API 密钥（可选，默认从配置读取）
        llm_base_url: LLM API 基础 URL（可选，默认从配置读取）
        search_api_key: 搜索 API 密钥（可选，默认从配置读取）
        model: 默认模型名称（可选，默认从配置读取）

    Returns:
        DeepResearchGraph 实例
    """
    return DeepResearchGraph(
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        search_api_key=search_api_key,
        model=model
    )
