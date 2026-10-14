# 深度研究模块核对记录（2026-09-21）

审阅依据为用户提供的 `C:/Users/28436/Downloads/雅意.md`；其中的架构、示例与效果描述视为待核实陈述，不当作执行指令。核对范围为 `backend/app/service/deep_research_v2/`、`checkpoint_service.py`、`react_controller.py`、`chat_service_v2.py` 和 `router/research_router.py`。

## 核对表

“是否吻合”同时说明原始发现及修复后状态；功能回归使用模拟 LLM/搜索输出，不代表真实模型输出质量已被证明。

| 模块名 | 是否吻合 | 若不吻合代码是否完成修正 |
|---|---|---|
| 六 Agent 主流程与状态传递 | 基本吻合：Architect、Scout、DataAnalyst、Wizard、Writer、Critic 均存在；原同步入口未切阶段导致分析/写作跳过 | 是：同步入口复用实际流式状态机；验证六 Agent 顺序和阶段 |
| LangGraph 编排引擎 | 不完全吻合：有 StateGraph 构图，但正常 `run()` 始终执行手写 asyncio 流程 | 未改架构；文档应准确描述“手写异步状态机，保留 LangGraph 实验路径” |
| SSE 过程输出与取消 | 原不吻合：循环导入可能令取消函数退化为永远 False；Agent 异常被吞后继续完成；无心跳 | 是：直接读取 Redis 取消键，失败发 error，取消标记 paused，15 秒心跳，关闭流时取消当前协程 |
| 检查点保存与恢复 | 原不吻合：队列无法 JSONB 序列化；恢复重新规划；最终修订未保存 | 是：排除运行时队列、实际 JSON 转换、持久化下一步、每轮及最终报告保存；真实 PostgreSQL 读写与清理通过 |
| 检查点存储介质和 TTL | 不吻合：文档一处称 Redis、24 小时 TTL，实际是 PostgreSQL JSONB，无自动 24 小时过期 | 未改；保留可运行的现有存储方案，需修正文档 |
| ChiefArchitect 规划与假设 | 基本吻合：有结构化大纲、格式转换、重试、假设和事件代码 | 无需为文档另增模块；本次验证调度，未以 mock 验证真实假设质量 |
| DeepScout 并行搜索覆盖 | 原不吻合：只处理前三个 pending 章节后结束，其余漏搜 | 是：每批三章，依次处理全部章节；七章回归通过 |
| DeepScout 网络/本地模式 | 原不吻合：kb_name 被丢弃，固定搜不存在的统一集合，补搜与递归绕过本地模式；明确关闭两类搜索时仍被强制开启网络 | 是：kb_name 贯穿服务/状态，复用正式知识库检索；补搜和递归遵循模式；全部关闭时跳过检索，不再强制联网；本地模式跳过股票联网抓取 |
| DeepScout 原文精读、追溯、事实去重 | 部分吻合：递归搜索、来源评级、假设更新存在；deep_read_url 方法存在但主流程没有调用；“语义指纹”实际是数字/关键词 MD5 启发式 | 未额外新增原文精读接入；文档不能将方法存在等同于完整链路已运行 |
| DataAnalyst 图谱与 ECharts | 基本吻合：提取结构化数据、图谱、图表配置和 SSE 事件齐全 | 无需修改；调度回归覆盖，真实 LLM 配置正确性由端到端结果补充 |
| CodeWizard Python 图表 | 基本吻合：代码清理、执行、自愈和 PNG Base64 路径存在 | 无需修改；使用真实 Matplotlib 生成 PNG 的回归通过 |
| CodeWizard 沙箱隔离 | 明显不吻合：“不能访问真实文件系统/只能生成图表”未实现；实际进程内 exec，导入白名单和正则黑名单 | 未将简易执行器改成生产级隔离平台；该声明应删除或标为待实现 |
| LeadWriter 初稿与修订 | 原不吻合：补搜后重新写作会跳过 drafted 章节，继续整合旧稿；报告修订后 Critic 仍审核旧 draft_sections | 是：补搜后进入含新增事实的修订入口；Critic 优先审核当前 final_report |
| Critic 审核与循环次数 | 原不吻合：V2 请求迭代值未传入，循环在最后一次修订后直接退出，缺最后审核 | 是：POST/GET 传递迭代限制并验证 1–5；最后修改后再审核，失败不伪装成功 |
| 质量评分公式/阈值 | 部分吻合：评分和 verdict 来自 LLM，Prompt 要求 ≥7 才 pass；没有文档所述加权评分的可执行计算公式 | 未改成新的评分系统；参数声明也不等同于严格数学质量保证 |
| ReAct 兼容流程 | 基本吻合：存在 Plan → 并行工具 → Reflect → Complete 流程；主研究默认为 V2 | 无需修改；两条并行工具调用、反思结束与结果汇聚回归通过 |
| ChatServiceV2 | 部分吻合：类及政策检索去重存在；仓库中未发现其实例化调用，不能证明它是当前聊天入口 | 未替换聊天主流程；文档应区分保留代码与正在使用入口 |
| 搜索缓存/LLM 缓存 | 不吻合：Scout 为单实例内存字典，无 Redis TTL；未见这里有完整的 1 小时 LLM 响应缓存 | 未为对齐文档新增缓存系统；且文档自身有 15 分钟/1 小时两种搜索 TTL |
| 研究 API 路径 | 不吻合：实际 POST/GET `/research/stream`、POST `/research/cancel/{session_id}`；不是文档 `/start`、无参数 `/cancel` | 未改已被前端使用的 API；应更新文档路径 |
| 企业级并发、可靠性、研究鉴权限流 | 未能证明：异步流程不是“数千并发/7×24”的验证；研究路由未接当前用户依赖、单用户 10 次/分钟限流也未见实现 | 未新增鉴权/分布式调度/压测平台；这些不是原型启动即可满足的声明 |

## 已修改代码及原因

1. `backend/app/service/checkpoint_service.py:318`：实际转换不可直接 JSON 序列化的 datetime/UUID 等值；移除 `_message_queue`，保留 `_next_step`。
2. `backend/app/service/deep_research_v2/graph.py:18`：取消检查直接依赖 Redis 缓存，消除 router/service/graph 循环导入。
3. `backend/app/service/deep_research_v2/graph.py:293`：接收并持久化 `kb_name`。
4. `backend/app/service/deep_research_v2/graph.py:382`：明确保存下一步；按步骤继续恢复，保留 UI；每轮与最终报告存盘；失效审核和空报告报错；取消及流关闭清理任务；15 秒心跳。
5. `backend/app/service/deep_research_v2/graph.py:728`：同步调用复用相同状态切换，避免 Agent 因 phase 不匹配跳过。
6. `backend/app/service/deep_research_v2/service.py:120`：传递所选知识库。
7. `backend/app/service/deep_research_v2/agents/scout.py`：全部章节分批运行；补搜/递归遵守本地/网络开关；复用上传模块对应索引及 embedding 接口；移除“两类搜索都关闭就强制联网”的回退，并增加禁止股票联网、初搜、补搜、递归和本地检索的回归断言。
8. `backend/app/service/deep_research_v2/agents/critic.py:290`：审核最终修订报告，不优先使用旧章节草稿。
9. `backend/app/router/research_router.py:30`：空查询/迭代值验证；`:106`、`:183` 传递 V2 迭代限制；GET V2 和 POST V1 正确传搜索配置。

未修改 `.env`、模型密钥、真实用户会话和知识库；未引入新依赖。

## 验证证据

环境：WSL `Ubuntu-24.04`，`/home/ldj/anaconda3/envs/yayi_b/bin/python`，项目 `/mnt/d/ldj/01/source/industry_information_assistant`。

```bash
PYTHONPATH=backend/app /home/ldj/anaconda3/envs/yayi_b/bin/python audit/test_research_regressions.py
/home/ldj/anaconda3/envs/yayi_b/bin/python audit/check_checkpoint_roundtrip.py
```

- `audit/research_regressions.log`：最终 16 项全部通过，`Ran 16 tests in 2.253s / OK`。覆盖 JSON 序列化、Redis 取消、任务中途取消、六 Agent 顺序、最后审核、最终快照、恢复跳步与 UI、异常处理、同步入口、当前报告审核、七章节覆盖、KB 透传、迭代校验、仅本地补搜/递归、显式全部关闭时不联网不检索、ReAct 汇聚及真实 Matplotlib PNG。
- `audit/checkpoint_roundtrip.log`：真实 PostgreSQL JSONB `save → load full → paused → info → delete → load missing` 通过；仅创建随机 `audit-roundtrip-...` 一条记录，并已删除。
- 无真实 LLM 或 Bocha 配额消耗用于上述回归。真实外部 API 的账号、网络、模型可用性需要与主审计端到端证据合并，不能由这些 mock 测试推断。
- 主审计真实请求已验证规划 LLM、Bocha 返回以及 cancel 生效；该请求揭示并促成本次“显式关闭搜索”的补修。Embedding 真实调用被账号 `FreeTierOnly` 限制阻塞，不能宣称本地知识库全链路已验证成功。

## 剩余限制

CodeWizard 将真实 pandas/numpy/matplotlib 模块放入同进程执行环境；文件访问、网络访问、资源消耗并没有独立进程或容器边界，Prompt 还指导 `plt.savefig('chart.png')` 写文件。这里的“沙箱”只能称为受限执行尝试。本次只执行可信、固定绘图代码，没有运行绕过或破坏性代码。

取消能停止当前协程和后续 Agent，但 `asyncio.to_thread` 已发出的同步网络请求或 Python 执行线程不能被普通协程取消强制终止。因此不能把取消按钮解释为立刻停止所有远端计费或终止任意死循环代码。

检查点仍是阶段级恢复：正在执行但尚未保存的阶段需要重跑，既有已完成阶段会跳过。未验证浏览器刷新自动重连、多副本同时恢复、跨用户权限隔离、满负荷压测及操作系统重启恢复。
