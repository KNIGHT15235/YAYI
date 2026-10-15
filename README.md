# YAYI 雅意 · AI-Scientist 科研助手

面向科研文献调研的本地 Demo，围绕文献检索、证据分析、综述写作、引用审核与可视化，展示可追溯、可修订、可恢复的多 Agent 研究流程。

**技术栈：** Python · FastAPI · asyncio · DeepSeek/Qwen · DocMind · Milvus · PostgreSQL · Redis · React/TypeScript · ECharts

当前执行器是六角色 **asyncio 异步状态机**，通过 `asyncio.Queue` 汇集事件、SSE 推送进度；不是依赖 LangGraph 执行的版本。本仓库是工程演示，不包含生产平台的文献规模、私有数据或服务能力。

## 科研流程

```text
研究问题 → Planner 规划 → Retriever 检索 → Analysis 评估证据
                              ↑                │
                              └── 证据不足：有界补检 ┘
                                               ↓
                              Visualizer 生成文献集图表
                                               ↓
                                     Writer 写作 → Reviewer 审核
                                               ↑          │
                             定向补检 / 重新分析 / 局部修订 ←┘
                                               ↓
                                    报告、引用与明确的质量状态
```

- **文献入库与追溯：** DocMind 解析文献，保存片段、独立资产和原文位置；embedding 与 Milvus 检索使用同一知识库身份，研究结果能回到同版本文档或表格资产。
- **知识库混合检索：** Milvus 向量召回与应用侧 BM25 独立召回，RRF 去重融合后使用现有重排服务；复用已有文本与片段 ID，兼容 Milvus 2.3.3。配置、缓存边界和回滚方式见 [混合检索方案与验证](docs/混合检索方案与验证-2026-10-15.md)。
- **统一证据：** 本地知识库与 Crossref/arXiv 学术记录进入统一来源和证据模型，区分文献数与片段数。只有摘要时明确限制，不声称完成全文精读。
- **写前与写后双闭环：** Analysis 判断证据覆盖，不足时有界补检；Reviewer 按声明核验，并决定补检、重新分析或局部修订。初检、补检共享总预算，恢复不重置消耗。
- **引用约束：** `quote_id` 绑定服务端原文、证据身份和版本，服务端回填引用；定位字段校验与结论支撑性审核分开，定位成功不等于事实正确。
- **状态与交互：** PostgreSQL 保存研究状态和 checkpoint，Redis 管理取消与研究租约；支持停止恢复、人工追加复核、旧报告归档及同会话防覆盖。
- **科研展示：** React 展示阶段进度、文献库、声明审核、知识图谱、ECharts 图表和报告。文献分布图仅描述本次检索集，不代表整个领域规模或方法性能。

## 本机 WSL 运行

以下是本次实际验收环境，而非克隆仓库后自动具备的配置：

| 组件 | 已验收配置 |
|---|---|
| WSL / Python | Ubuntu-24.04 / Conda `yayi_b`，Python 3.10.21 |
| 前端 | http://localhost:5199 |
| 后端接口文档 | http://localhost:8029/docs |
| PostgreSQL | `localhost:15432`，数据库 `yayi_0929` |
| Redis | `localhost:16379`，研究租约与取消使用 DB `9` |
| Milvus | `localhost:29530`，数据库 `yayi_0929` |

首次部署需要安装后端与前端依赖、准备基础服务，并将 `backend/.env.example` 复制为 `backend/.env` 后填写自己的连接配置和凭据。已有配置不要覆盖。前端本地环境需配置 `VITE_API_BASE=/api`、`VITE_API_PROXY=http://127.0.0.1:8029`；详情见 [后端说明](backend/README.md) 与 [前端说明](frontend/README.md)。

在本机已配置的环境中，分别启动两个 WSL 终端：

```bash
# 终端一：后端；显式使用本次账户已验证可用的模型
cd /mnt/d/ldj/01/YAYI_0929/backend
DEFAULT_MODEL=qwen-plus NEWS_COLLECTION_ENABLED=false MEMORY_AUTO_ENABLED=false \
  /home/ldj/anaconda3/envs/yayi_b/bin/python app/app_main.py
```

```bash
# 终端二：前端
cd /mnt/d/ldj/01/YAYI_0929/frontend
node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5199 --strictPort
```

模型优先级为角色 `*_MODEL` > `DEFAULT_MODEL` > 已保存的配置/默认值，具体模型需在所用供应商账户中可用。服务已运行时不要重复启动；端口冲突先确认占用进程。不要在研究运行中修改前端源码触发热更新，否则 SSE 断开会按中断处理。

六角色的默认请求参数如下，统一维护在 `backend/app/config/llm_config.py`，同时应用到科研与行业流程。`max_tokens` 是每次调用的输出上限，不是输入上下文容量，也不保证模型一定生成完整 JSON。

| 角色 | 默认模型 | temperature | max_tokens |
|---|---|---|---|
| ChiefArchitect | deepseek-v3.2 | 0.3 | 16000 |
| DeepScout | qwen-plus | 初检 0.2；补检 0.1 | 8000 |
| DataAnalyst | qwen-plus | 0.2 | 8000 |
| CodeWizard | deepseek-v3.2 | 0.1 | 6000 |
| LeadWriter | deepseek-v3.2 | 初稿 0.4；定向修订 0.1 | 16000 |
| CriticMaster | deepseek-v3.2 | 0.2 | 16000 |

上面的 WSL 历史验收命令显式设置了 `DEFAULT_MODEL=qwen-plus`，会覆盖此表的模型默认值。要采用此表，请移除该覆盖，并确认环境与 `.env` 中没有其他模型覆盖；恢复旧会话仍保留检查点中的模型选择，显式环境配置优先。模型服务必须支持所选模型及当前调用使用的 JSON 输出。

科研 CodeWizard 调用模型为已计算的年份/方法关键词分布选择图表类型和布局；服务端校验方案并填入真实统计值、标签及证据来源。模型不生成或执行计算代码。设计服务失败或方案无效时使用统计柱状图模板，并在 `visualization_plan` 与进度事件中记录降级；没有可绘制统计时跳过模型调用。

本次默认配置调整通过 Windows Python 3.12 下的 319 项相关离线回归（外部连接禁用，事件循环使用内部 loopback socketpair）。新增 `audit/test_agent_request_configuration.py` 直接核对模拟 SDK 收到的参数，覆盖六角色、补检/修订切换、图表方案校验、数据来源保护及取消/降级。这不代表已完成新配置的真实供应商联调。

不同机器请替换上述路径和端口。不要重复启动与既有服务同名、同端口的容器，也不要为运行 Demo 清空数据库。真实模型、文档解析、embedding 和重排调用可能产生供应商费用。

## 体验科研链路

1. 登录后创建知识库，上传可用于测试的文献，确认解析与索引完成。
2. 在“深度研究”选择知识库或全部搜索，提出明确的科研问题和范围。
3. 观察检索、分析、补检、写作和审核事件；点击报告引用查看原文摘录与资产。
4. 长任务可停止后恢复；新研究使用“新建研究”，不覆盖原会话。
5. 对已结束报告使用“追加复核”，选择声明并填写具体意见，比较归档与修订结果，同时检查质量状态。

示例问题：

> 围绕2020–2026年光学遥感图像变化检测方法开展文献调研，比较主要方法、评价设置与证据局限，生成带引用的文献综述。

仓库不附带测试账号、已上传文献或研究历史；克隆后需要自行创建测试资源。

## 验证与当前边界

最新 WSL 验证：后端离线 **389/389（22模块）**。前端未改，沿用辅助逻辑 **29/29**、TypeScript 和生产构建通过的基线。此前真实 DocMind、DashScope、Milvus、PostgreSQL、Redis 及浏览器全链已执行；混合研究实际完成两轮写前补检和两轮审核后补检。

后续已修复原文可用性误判、显式领域否定外推与人工状态耦合：审核逐引用返回支撑关系，非法结果定向重试；人工请求冻结原文基线，分别记录正文实施和目标审核。新会话经真实检索、人工修订和复审，30条声明获本轮模型支持、报告passed/confirmed；中间实测人工applied=true时其他自动问题仍未核验，跨轮状态正确保留。旧失败报告没有改写。完整过程见 [审核质量与人工状态复验](docs/审核质量与人工状态复验报告-2026-10-15.md)。

**模型审核通过仍需独立质量评测。** 本轮只有合成工程材料和小样本反例，有限规则不能识别所有语义外推。当前仍是进程内执行器，未实现独立Worker、持久化任务队列或exactly-once语义。

合成测试材料只验证工程链路，不能用于证明 Recall@20=91% 或引文事实错误率12%→3%。任意 PDF 字符级高亮、图像事实理解、正式质量评测与生产性能也不属于本轮已通过范围。

```bash
# 在仓库根目录运行；完整22模块命令见最新复验报告
/home/ldj/anaconda3/envs/yayi_b/bin/python audit/live_acceptance.py preflight

cd frontend
npm run test:workflow
npm run typecheck
npm run test:build
```

`preflight` 只检查现有配置与服务，不输出密钥；前端辅助逻辑测试不是浏览器端到端测试的替代。

## 文档与目录

- [科研流程改进方案与推进进度](docs/科研流程改进方案与进度.md)
- [审核质量与人工状态复验](docs/审核质量与人工状态复验报告-2026-10-15.md)
- [WSL真实全链路验收报告与复现步骤](docs/WSL真实全链路验收报告-2026-10-14.md)
- `backend/`：FastAPI、科研 Agent、文献解析与检索、证据和任务状态。
- `frontend/`：科研交互、原文预览、审核面板与图表。
- `audit/`：离线回归、隔离故障与真实服务验收脚本。
- `docs/`：方案、进度与验收记录；较早文档描述历史版本，以进度及最新复验报告为准。

仓库只发布源码、配置示例、测试脚本与脱敏文档。`.env`、访问凭据、上传文献、解析资产、运行快照、日志、依赖和构建目录均不随版本发布。不要上传 `backend/storage/` 下的运行记录或凭据。
