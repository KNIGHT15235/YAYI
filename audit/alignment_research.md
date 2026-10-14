# 研究后端功能补齐记录

本轮在原有可运行架构内直接补齐研究功能，没有切换执行引擎。变更前文件备份位于 `audit/alignment-before/`，仅补缺失备份，未覆盖已有备份。此前 `research_findings.md` 是第一轮历史核对，以下状态优先于其“未实现”结论。

## 本轮核对表

| 模块名 | 是否吻合 | 若不吻合代码是否完成修正 |
|---|---|---|
| DeepScout 原文精读 | 原先方法未调用；现在在章节搜索后、事实提取前接入 | 是；每项研究最多尝试 3 个唯一 URL，成功结果传入分析 Prompt 并保存 raw_sources |
| 原文抓取边界 | 文档未明确；已限定为公开 HTTP(S) HTML/文本 | 是；校验 DNS 所有地址、固定已校验 IP 建连、HTTPS 保留 SNI/证书主机校验、逐跳重定向复查，拒绝私网/回环/链路本地/非标准端口 |
| 精读预算、超时和降级 | 文档原先无限定，现有明确边界 | 是；最多 3 次，抓取预算 10 秒、调用等待 12 秒、精读含模型总等待 25 秒，最多 3 跳重定向、响应最多 1 MB；失败保留摘要继续 |
| 搜索开关 | 网络、本地、都关闭均被遵守 | 是；关闭网络不会抓取原文；本地搜索校验当前用户的所选知识库 |
| Redis 搜索缓存 | 原先实例内存字典，无 TTL；现在符合 15 分钟版本 | 是；共享 RedisJSONCache，TTL=900 秒，SHA256 键包含 query/count/freshness；缓存故障降级到正常 API 调用 |
| LLM 响应缓存 | 原先无；现在有 1 小时缓存 | 是；只缓存认证研究 Agent 的成功非空非流式响应；键含用户、账号密钥不可逆哈希、endpoint 和完整调用参数；匿名直接调用不启用 |
| Critic 加权评分 | 原先直接信任模型总分；现在实现文档公式 | 是；五维 1–10 数值校验并计算 0.3/0.3/0.2/0.1/0.1；总分 ≥7 且无 critical/major 问题才通过；无效评分仅纠正重试一次，仍失败则保留报告并明确质量待确认，分数为 null、不沿用旧稿分数 |
| 研究鉴权 | 原先研究路由匿名可访问；现在强制认证 | 是；全部 9 条研究路由，包括诊断入口，要求 Bearer Token |
| 会话/检查点归属 | 原先可按任意 session_id 读取、覆盖、删除或取消 | 是；校验 ChatSession/ResearchCheckpoint 所有权，未知及他人 ID 统一 404；列表及保存/读取/删除按 owner 限定 |
| 旧检查点兼容 | 未归属记录不能可靠确定主人 | 部分；仅当其关联 ChatSession 归当前用户时绑定旧 NULL owner；无可证明归属的独立匿名历史记录不会自动认领 |
| 同用户并发与重复研究 | 原先没有限制；现在防重复执行 | 是；Redis Lua 原子获取用户和会话租约，每用户 1 项、每会话 1 项；重复会话 409，同用户并发 429 |
| 启动请求限流 | 原先缺失；现在落实文档 10 次/分钟 | 是；Redis 服务器时间和 ZSET 计算滚动 60 秒，启动/恢复合计最多 10 次；超限 429，Redis 不可用时 503，不绕过限制 |
| SSE 断开与租约释放 | 原先多层 async generator 的关闭可能延迟传递 | 是；显式逐层 aclosing，立即取消 Agent 协程并保存 paused；结束或断开释放租约；租约 120 秒过期，每 30 秒续期 |
| 图表完整性 | 原先已有数据点被图表门槛漏算，同次只抓最后 figure | 是；已有 data_points 可生成 ECharts；捕获全部新 figure，章节图表也逐一保存；Wizard 绘图加锁；SSE 使用稳定 chart id |
| 最终图表/图谱恢复 | 原先最终事件只给图表数量 | 是；research_complete 附 charts、knowledge_graph、quality_dimensions，前端负责按 ID 去重展示 |
| LangGraph 主执行 | 仍与“使用 LangGraph 为主引擎”不吻合 | 保留手写 asyncio 流程；切换会要求重做取消、实时 SSE、检查点恢复和补搜路由，不能只改开关冒充完成 |
| 操作系统级代码沙箱 | 仍与“不能访问真实文件/禁止网络/只能生成图表”不吻合 | 未伪造隔离；当前仍是同进程 exec 加白名单/黑名单，需要按下表修正文档 |

## 修改文件与关键位置

- `backend/app/service/deep_research_v2/agents/scout.py:1075`：15 分钟搜索缓存；`:1192` 原文预算与降级；`:1221` 有界原文获取。精读结果进入章节分析 Prompt，不仅发送 UI 日志。
- `backend/app/service/deep_research_v2/safe_fetch.py:15`：URL/DNS 校验；`:38` 固定公共 IP 的 HTTP(S) 获取和每跳检查。没有依赖会再次解析原主机的 requests.get，也不读取系统代理、Cookie。
- `backend/app/service/deep_research_v2/agents/base.py:65`：1 小时 LLM 缓存；`graph.py:352` 设置认证用户作用域。复用主审计提供的 `service/response_cache.py`，Redis 连接/读取超时 0.3 秒，单值最多 2 MB。
- `backend/app/service/deep_research_v2/agents/critic.py:164`：校验维度、一次纠正重试，失败保存报告并标记质量待确认；有效评分覆盖模型随意给出的总分/通过结论；`_weighted_score` 严格校验后加权计算。
- `backend/app/service/research_access.py:9`：会话归属校验和可证明归属的旧记录绑定。
- `backend/app/service/research_guard.py:45`：跨 worker Redis 租约、原子限流、token 比较后续期/释放；不会由另一个请求误删正在运行的锁。
- `backend/app/router/research_router.py:70`：启动鉴权、知识库归属、预保存可恢复状态；`:178` 恢复鉴权。GET 流式入口复用 POST 逻辑，所有 SSE 仍使用原事件格式及 `data: [DONE]`。
- `backend/app/service/checkpoint_service.py:29`：用户过滤；`:35` 拒绝跨用户覆盖、更新查询并清除过期报告/错误信息。
- `backend/app/service/deep_research_v2/agents/data_analyst.py:416`：补上已有 data_points 的图表资格判断。
- `backend/app/service/deep_research_v2/agents/wizard.py:1091`：研究绘图串行化；`:1267` 捕获全部新 figure；`:701` 同次章节输出逐一保存并发送稳定 ID。
- `backend/app/service/deep_research_v2/service.py`、`graph.py`：`contextlib.aclosing` 确保外层 SSE 关闭传递到实际运行协程；最终事件补图表、图谱和评分维度。

## 验证

使用原 WSL Ubuntu-24.04 的 `/home/ldj/anaconda3/envs/yayi_b/bin/python`，未新增依赖或修改 `.env`。

```bash
PYTHONPATH=backend/app /home/ldj/anaconda3/envs/yayi_b/bin/python audit/test_research_regressions.py
/home/ldj/anaconda3/envs/yayi_b/bin/python audit/test_alignment_research.py
```

- 原流程及新断开回归 **18/18 通过**：`audit/alignment_research_regressions.log`，`Ran 18 tests in 4.885s / OK`。新增完整 SSE 与检查点回归覆盖末轮评分为 0 或 80 的无效结果，保证一次重试后仍能保留最新报告并明确质量待确认。
- 本轮新增对齐回归 **24/24 通过**：`audit/alignment_research_tests.log`，`Ran 24 tests in 2.219s / OK`；新增纠正 Prompt 重试成功、重试服务失败后保留报告，以及 Prompt 示例本身是合法 JSON 且示例加权计算一致的测试。
- 真实 Redis 验证了原子重复会话拒绝、单用户并发拒绝、错误 token 无法释放他人租约、10 次滚动限流，以及 SSE 完成/提前关闭后立即释放租约。全部使用随机 `audit-...` 键并在 finally 删除。
- HTTP 认证、归属、SSRF、精读预算/降级、缓存和评分测试均模拟外部服务；图表测试真实调用 Matplotlib 生成两张 PNG。未借这些测试宣称外部模型输出必然正确。
- 主审计准备的 `audit/smoke_alignment_research.py` 与新认证/恢复协议兼容；生产重启和真实模型验收由主审计统一执行，其结果另见主报告。

### 真实模型末次审核错误的补充修正

首次真实恢复已产生 3 张图表和修订后的 1828 字符报告，但第二次审核因 `source_completeness` 不在 1–10 内抛出异常，最终未发送完成事件。日志没有记录具体分值，不能据此断言是 0 分或百分制。这是审核异常未降级，不是 SSE JSON 序列化失败。

修正后最多进行一次要求更严格且缓存键不同的纠正重试；仍失败时保存报告，`quality_score=null`、`quality_dimensions={}`、`quality_review_status=unconfirmed`，通过审核事件、警告及最终事件说明“质量待确认”，不保留旧稿的 8.5 分。有效返回才按原公式计算分数，绝不将 80 等未知尺度值夹取为 10 分。

恢复时保留检查点的 `max_iterations`，不会以服务默认 3 覆盖。该上限表示修订次数；值为 1 允许初审、一次修订及修订后复审，因此可能出现两次审核。真实测试若只验证初审终态，可将合成检查点的 `iteration` 设置为上限。

### 独立真实 Critic 验证与证据边界（评分修复前的历史记录）

评分修复前，主审计恢复测试产生2255字符报告、2张图表并保存完成检查点，但两次审核都返回越界维度，因此当次结果为 **9/11**，评分为`null`。原始结果已保存在`audit/scoring-before/alignment-research-live-results.json`，相关旧服务日志为`audit/backend-alignment-final.log`，不能用独立探针替换该次失败。

2026-09-22后续评分修复已完成：Critic独立使用qwen-plus，先核查后评分，反馈具体错误进行一次纠正，并绕过共享LLM响应缓存。最终恢复测试 **11/11**，从零启动的规划、检索、分析、图表、写作、审核、修订及复审 **47/47**；后者最终有效评分10.0且审核pass，研究回归 **47/47**、真实正反评分 **2/2**。新证据与修改说明见[评分全流程修复报告](评分全流程修复报告.md)；下文DeepSeek探针保留作历史对照。

只读检查发现 Prompt 中标为 JSON 的示例使用 `1-10` 数字和 `true或false` 布尔，占位写法不能被 JSON 解析。已改为合法示例，注明示例分数不是预设结论，并在系统提示中明确五维最低 1、最高 10。此处修正了可证明的格式矛盾，不能据此断言它是先前所有模型越界的唯一原因。

`audit/probe_critic_live.py` 仅以自有合成文本调用真实 Critic，不创建用户、会话、检查点，不联网检索。结果见 `audit/critic-live-results.json`（含两次原始响应）和 `audit/critic-live.log`：模型 `deepseek-v3.2`，30.47 秒；首次 `objectivity=-1` 被拒绝，唯一一次纠正重试返回五维均为 1，后端按权重计算 **1.0**，`quality_review_status=confirmed`、`verdict=needs_revision`，报告保持且流程结束。模型自报总分为 -1，不参与最终计算；无夹取、补造或沿用评分。这验证了真实五维结构与确定性加权链路，**不代表报告质量通过或模型事实判断可靠**。模型对已明确标为合成的数据仍提出严重质疑，体现了质量维度判断本身的主观性。

## 原《雅意.md》精确行号与替换建议

以下行号来自本机 `C:/Users/28436/Downloads/雅意.md`（原文件未被本代理改写）；范围包含需要替换的原段落。为便于主审计直接制作修订版，替换文字可直接使用。

| 原文行号 | 原陈述/问题 | 建议替换文字 |
|---|---|---|
| 13 | 微服务、高并发、7×24 可靠性被写成既成能力 | 当前原型采用 FastAPI 应用和 Docker 管理的基础服务，使用异步任务与 Redis 缓存改善 I/O 响应。尚未进行生产容量与可用性验收，不承诺 7×24 或指定并发数。 |
| 23 | 多智能体编排引擎（LangGraph） | 多智能体编排采用手写 asyncio 状态机和消息队列：Architect → Scout → DataAnalyst → Wizard → Writer → Critic。保留 LangGraph 构图代码用于实验，当前生产入口不执行它。 |
| 42–45 | `/start` 和无 ID 的 `/cancel` | `POST /research/stream` 启动 SSE；`POST /research/cancel/{session_id}` 取消；`GET /research/checkpoint/{session_id}` 获取元信息；`GET /research/checkpoint/{session_id}/full` 获取完整状态；`POST /research/resume/{session_id}` 恢复。上述接口均要求当前用户 Bearer Token 与会话归属校验。 |
| 174 | Redis 检查点、TTL 24 小时 | 完整研究状态、UI 状态和最终报告保存在 PostgreSQL JSONB 检查点中，按阶段和审核循环保存，不设置自动 24 小时过期。Redis 用于取消标志、运行租约和缓存。此项应移到 PostgreSQL 存储描述。 |
| 176 | 会话状态仅笼统描述 | Redis 保存取消标志（5 分钟）以及单用户/单会话运行租约（120 秒，运行中每 30 秒续期）。连接结束或任务取消会释放租约，进程退出后的残留租约自动过期。 |
| 178、230、530 | 搜索缓存混用 1 小时、15 分钟、内存 | Bocha 搜索结果使用 Redis 缓存，TTL 为 15 分钟。缓存键包含查询、返回数量和 freshness；Redis 不可用时回退到正常搜索调用，不缓存请求失败。 |
| 234 | 仅“相同 Prompt 1 小时”未包含用户和配置 | 认证研究 Agent 的成功非流式 LLM 响应缓存 1 小时。缓存键包括用户、账号不可逆哈希、API endpoint、模型、完整消息、温度、max_tokens 和 response_format；不跨用户复用，匿名调用不启用此缓存。 |
| 264 | 单用户每分钟 10 次，不说明并发 | 每个用户滚动 60 秒内最多启动或恢复 10 次研究，并且同时最多运行 1 项；同一会话不能重复启动。超限返回 429，重复运行会话返回 409；Redis 调度不可用时返回 503。 |
| 276、390 | 数千并发、单机 200–300 并发 | 已实现异步执行、每用户并发限制和跨 worker Redis 租约。系统容量仍取决于 API 配额、数据库、硬件和生成代码耗时；尚未压测验证具体并发数。 |
| 298 | 固定模型单价、笼统成本结论 | Agent 可分别配置模型，当前 Scout 使用 qwen-plus，其他研究 Agent 默认 deepseek-v3.2。费用按实际模型服务、地域、输入/输出 token 和账号计费规则计算，不在项目文档中硬编码单价。 |
| 308 | 检查点恢复没有说明重做粒度 | 研究在阶段结束和审核/修订循环后保存检查点；恢复跳过已保存的完成阶段，重新执行未完成阶段。已发出的同步网络或代码执行线程无法由普通协程取消强制终止。 |
| 310 | 前端 EventSource 自动重连 | 前端使用携带 Bearer Token 的 POST/fetch 读取 SSE，后端约每 15 秒发送空闲心跳。连接中断后通过完整检查点恢复 UI，并显式调用 resume；不依赖 EventSource 自动重放。 |
| 312 | 严格沙箱、不能访问文件、只能生成图表 | CodeWizard 在后端进程中执行生成的 Python 代码，使用导入白名单和正则黑名单减少误操作，支持最多 3 次修复。该机制没有独立进程/容器、文件系统、网络或资源隔离，不能称为安全沙箱，也不能保证仅生成图表。 |
| 341、362–364 | “隔离文件系统”与无法访问真实文件 | 小节改为“受限代码执行机制”。将这三行注释替换为：`# 捕获图表到内存 Buffer 供前端显示`、`# 生成代码仍运行在真实后端进程中，未提供文件系统/网络隔离`、`# matplotlib 保存到 Buffer 不等于禁止 pandas/numpy 等模块访问文件`。 |
| 367 | 异步无 GIL 限制、不创建线程 | 异步适合搜索和模型 API 等 I/O 等待；本项目也通过 asyncio.to_thread 调用同步 SDK 和绘图代码。异步不消除 GIL，也不能自动把 CPU 密集任务变为多核并行。 |
| 376 | 搜索缓存 Key=MD5(query) | 搜索缓存使用规范化 JSON（query、count、freshness）的 SHA256 键，存储于 Redis，TTL 为 15 分钟。不同返回数量和过滤配置不会误命中同一缓存。 |
| 384 | 把 LangGraph 当成现用框架 | 选择显式状态机是为了让阶段、取消、恢复和补搜路由可控。现用执行器是 asyncio；LangGraph 是保留的实验实现，尚未接入主执行入口。 |
| 394–396 | 两个框架可直接切换 | 小节名改为“当前 asyncio 状态机与保留的 LangGraph 实验实现”。当前入口固定执行 `_run_simplified`；LangGraph 路径缺少与现有 SSE、恢复和补搜一致的行为，不能直接切换为等价生产流程。 |
| 410 | 实验图说明与实际节点不符 | 保留的 LangGraph 实验路径为 plan → research → analyze（仅 Wizard）→ write → review → revise 或结束；没有完整接入 DataAnalyst、补充搜索和阶段检查点恢复，当前不作为运行入口。 |
| 420 | 仅阶段前检查取消 | 运行时约每 0.5 秒检查 Redis 取消标志，并在阶段之间检查；SSE 关闭时逐层关闭生成器并取消当前 Agent 协程。同步 SDK 请求和 exec 线程不具备强制中断保证。 |
| 554 | 原文精读无预算/失败边界 | 主流程在章节搜索后调用原文精读，每项研究最多尝试 3 个唯一公开 URL，仅在网络搜索开启时执行；每篇精读等待最多 25 秒，抓取限制 1 MB、10 秒和 3 次重定向，失败降级到搜索摘要。DNS/重定向检查拒绝私网目标，并固定已校验公共 IP 建连。 |
| 566 | Scout 固定 max_tokens=8000 | Scout 默认使用 qwen-plus；章节搜索分析温度为 0.2，未单独覆盖的调用使用 BaseAgent 的 max_tokens 默认值 16000，具体调用以代码参数为准。 |
| 588 | DataAnalyst 模型写成 qwen-plus | DataAnalyst 当前配置为 deepseek-v3.2。数据提取与图谱构建温度为 0.2，图表配置生成温度为 0.3；未显式覆盖的 max_tokens 为 16000。 |
| 630–636 | 安全沙箱、禁用网络的绝对承诺 | CodeWizard 使用同进程受限 exec，预导入数据分析模块，捕获标准输出及本次创建的全部 figure，并转为 PNG Base64。白名单/黑名单不能替代操作系统级隔离；禁止直接导入 requests 等模块不等于阻断所有网络访问。 |
| 640 | 预设中文字体即可避免乱码 | 代码配置中文字体候选列表；实际字体能否显示取决于部署环境已安装字体，预设名称本身不能保证不存在中文乱码。 |
| 648 | Wizard max_tokens=4000 | CodeWizard 默认 deepseek-v3.2，基础温度 0.3，代码修复温度 0.2；当前未显式覆盖的 max_tokens 为 16000。 |
| 785 | 优先审核 draft_sections | Critic 优先审核当前 final_report，只有报告为空时才回退拼接 draft_sections，避免审核修订前旧稿；报告输入仍按 8000 字符截断。 |
| 789 | 公式可保留，但容易被读为客观测量 | LLM 提供五个 1–10 维度分，后端校验并按原公式加权得到最终 quality_score。无效结构/缺失/越界仅纠正重试一次，仍无有效分数时保留报告并标记质量待确认（quality_score=null），不夹取为满分、不沿用旧稿评分。加权是确定性计算，维度判断仍来自模型，不是独立事实验证。 |
| 793、797、799 | 旧 `_should_revise` 决策被误写成现主流程 | 当前 asyncio 流程由 Critic 的 phase 决定补搜、修订或结束；默认最多 3 次修订，接口允许 1–5 次。每次修订后都会再审核；只有加权分 ≥7 且没有 critical/major 问题才通过。达到迭代上限则完成并发送仍有问题的警告，不代表质量已达标。 |
| 813 | “在沙箱内执行” | 使用同进程受限 Python 执行器运行代码，捕获本次生成的全部图表并转为 Base64，保存到 charts 并通过带稳定 ID 的 chart 事件发送；此执行器不具备操作系统级隔离。 |

## 没有伪装完成的部分

LangGraph 主流程迁移、真正进程/容器级代码隔离、可强制终止任意生成代码、生产并发容量与 7×24 可用性仍未完成。它们需要专门的架构设计和验收，不能靠注释、正则或改一个调用开关得到保证。

精读只读取公开静态 HTML/文本，不运行浏览器 JavaScript，也不承诺付费墙、验证码和登录页面可访问。取消后的线程请求可能仍在远端完成。评分是模型维度判断加确定性加权，不保证事实绝对正确。

当前没有改变旧知识库“按名称对应集合”的布局，研究路由复用主审计的知识库归属/同名冲突检查；embedding 模型账号配额仍是独立外部前提，不通过代码伪造可用性。
