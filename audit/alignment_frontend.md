# 文档功能补齐：前端核对记录

日期：2026-09-21 至 2026-09-22。范围：`frontend/`；后端接口由其他专项核对负责。对照原文件 `C:/Users/28436/Downloads/雅意.md`，下列行号按该原文件当前内容计算，未直接修改该文件。

## 已补齐的能力

| 模块 | 原文位置 | 当前实现与结果 | 是否完成 |
|---|---|---|---|
| 研究恢复 | 第 11、308 行 | 聊天页读取完整检查点，恢复已有步骤、来源、图表和报告草稿，再 POST 恢复接口并消费 SSE；处理 `research_resumed`，结束后保存最终助手消息并刷新检查点状态；非 2xx 流式响应能读取后端 detail。 | 是 |
| 研究图表 | 第 31 行 | 接收中间 `chart`/`charts` 和结束事件中的图表与知识图谱，按稳定 ID 合并；报告中的 `![标题](chart_id)` 优先按 ID 插入图表，兼容旧标题匹配，真实图片链接保留；Base64 图片懒加载。 | 是 |
| 聊天手动保存记忆 | 第 866 行 | 会话增加“保存为记忆”，调用现有 `/memories/create`；成功显示确认，后端 warning 原样提示（包括索引降级或尚有待处理长会话尾部），503 等错误显示真实原因；请求中防重复点击。 | 是 |
| Markdown | 第 31、260 行 | 增加 highlight.js 代码高亮、KaTeX 行内/独立数学公式；保留表格样式与图片懒加载；渲染后统一 DOMPurify 清洗，保留数学 SVG/MathML；代码与图片属性转义，KaTeX `trust:false`。 | 是 |
| Text2SQL 图表 | 第 212 行 | 根据实际 `visualization_hint` 使用 ECharts 渲染 bar/line/pie/scatter；数值字符串转换，空值保留；数据不足、非数值或 table 类型时保留原表格，不伪造图形。 | 是 |
| 知识库检索 | 第 180–194 行 | 所选知识库新增问题输入和检索按钮；显示段落、文档名、切片号、原始余弦相似度、可选重排分数与警告；查询词使用 React 文本节点高亮。 | 是 |
| 原文件下载 | 第 194 行 | 文档列表与检索结果均提供原文件按钮；带 Bearer 请求并以 Blob 下载；已被旧版本清理的文件明确显示不可用/需重新上传。 | 是，旧文件不可凭空恢复 |
| 研究选择本地知识库 | 第 184 行 | 启用本地搜索后显示当前用户知识库选择器，发送所选知识库名称 `kb_name`；未选择时阻止发送并提示。与后端归属校验/必填规则对应。 | 是 |
| TypeScript 完整性 | 工程质量项 | 原有 23 项诊断全部修复：ECharts 类型、React 图标 cloneElement、Marked 扩展类型、步骤 searching/researching 和 subtitle、可选值处理及未使用代码。未通过删功能绕过检查。 | 是，0 项诊断 |

## 主要文件

- `frontend/src/pages/chat/index.tsx`：恢复流程、保存记忆、SSE 状态合并及检查点恢复。恢复入口约第 1482 行，记忆入口约第 1503 行。
- `frontend/src/api/session.ts`：恢复接口约第 234 行；`frontend/src/api/memory.ts`：记忆索引状态与 warning 类型；`frontend/src/api/request/error.ts`：解析流式错误响应。
- `frontend/src/pages/chat/shared.ts`：稳定 ID 合并图表；`frontend/src/pages/chat/component/research-detail/process-report.tsx`：报告图表占位符匹配。
- `frontend/src/components/markdown/index.tsx` 与 `index.scss`：代码高亮、数学渲染与安全清洗。
- `frontend/src/pages/database/query-visualization.tsx`（新增）：图表配置和渲染；数据库页保留数据表。
- `frontend/src/pages/knowledge/search.tsx`（新增）、`frontend/src/api/knowledge.ts` 与知识库页：检索、文本高亮和原文件下载。
- `frontend/src/components/sender/index.tsx`、`frontend/src/store/device.ts`：本地知识库选择。
- `frontend/package.json`、`package-lock.json`：新增 `highlight.js`、`katex@0.16.22`、`marked-katex-extension`，锁文件同步；使用现有 Node 18 环境兼容版本。
- 其余变更主要为上述类型错误修复。修改前文件备份在 `audit/alignment-before/frontend/`，未覆盖上一轮备份。

## 原文仍应调整的准确位置与可直接替换文字

下列差异属于实际技术方案或产品组织方式。为保持现架构，本轮不另造一套身份验证、SSE 自动重连或无需求的页面组织。

| 原文行 | 差异 | 建议替换整行文字 |
|---|---|---|
| 17 | 实际 React 19；使用 ECharts，未使用 Recharts；原文拼写有误。 | `1. 前端展示层（Frontend）：React 19 + TypeScript + Ant Design 5.x + ECharts 5.x + Marked + highlight.js + KaTeX + DOMPurify。` |
| 19 | 实际是 SSE，非 SSR。 | `2. API 网关层（FastAPI）：路由管理 + 鉴权 + 会话管理 + SSE 流式输出。` |
| 31 | 能力已补齐，但实际标签为搜索结果/知识图谱/可视化图表/过程报告，最终报告在过程报告中展示。 | `关键组件：研究详情面板实时显示研究进度，提供搜索结果、知识图谱、可视化图表、过程报告四个标签；过程报告可展示草稿和最终报告，并接收 SSE 更新与检查点恢复。Markdown 渲染器支持代码高亮、数学公式、表格样式、图片懒加载和 DOMPurify 清洗。图表组件支持 ECharts 配置、Base64 图片和自适应容器。` |
| 186 | 已接通的真实检索路由不同。 | `→ API：POST /knowledge-bases/{kb_id}/search，提交 query、top_k 和 rerank，并校验知识库归属。` |
| 194 | 下载为鉴权接口；旧版本已删除的原文件不存在。高亮是查询文本匹配，不宣称语义级逐词标注。 | `→ 返回结果给前端：展示相关段落并高亮匹配的查询词，显示原始余弦相似度及可用时的重排分数；提供带鉴权的原文件下载，历史原文件缺失时提示重新上传。` |
| 272 | 无自动重连；恢复是显式按钮和持久化检查点。 | `【P00-Q02】【SSE 连接中断怎么办？】页面停止读取后可重新打开会话，通过“继续研究”读取最近检查点并重新建立 SSE 流；是否继续运行受后端任务状态约束，当前未实现浏览器自动重连。` |
| 310 | 实际 POST + Fetch ReadableStream，需要请求体与 Bearer；不是 EventSource，也没有自动重连。 | `【M01-Q08】【为什么采用 SSE】研究过程主要由服务器向客户端推送进度，单向通信足够。后端流式输出 SSE，前端通过携带 Bearer Token 的 POST 请求与 Fetch ReadableStream 读取事件；中断后可基于检查点手动恢复，无需额外 WebSocket 协议。` |
| 339 | 同段既称 localStorage 又称 HttpOnly Cookie/CSP；当前实现不使用后二者，身份校验仍查询用户。 | `【M01-Q13】【为什么使用 JWT】项目使用 JWT Bearer 认证：登录后令牌由前端存储在 localStorage，并在请求头发送 Authorization: Bearer <token>。后端验证签名和过期时间，并查询当前用户状态。Markdown 输出使用 DOMPurify 清洗，代码与图片属性进行转义以降低 XSS 风险；当前实现未采用 HttpOnly Cookie，也未建立完整的生产 CSP 策略。这是当前原型的认证实现，不能将 JWT 等同于完全不访问数据库或不需要任何服务端状态。` |

第 866 行的手动按钮已实现；自动与定期压缩由后端记忆专项实现并验证，应与其结论一起核对，不再以“前端无保存按钮”列为缺失。第 202 行的数据库真实路由、Rerank 是否可用等后端描述以主报告为准。

## 验证与证据

测试运行环境为用户配置的 WSL Ubuntu-24.04，项目原有前端依赖环境。

1. `node audit/alignment_frontend_regression.cjs`：通过。覆盖 9 组专项场景：Markdown 高亮/KaTeX/MathML/XSS/懒加载；4 类 SQL 图表及缺数据降级；报告 ID 映射、去重、真实图片保留；质量审核无效/null 分数与显式需修订结论；安全段落高亮；真实知识库组件接收 null/非有限余弦与重排分数；记忆页面隐藏内部字段并保留业务信息；Bearer Blob 下载和 404 提示；真实 Chat 组件的暂停检查点恢复、分段 SSE、原来源保留、图表去重、最终报告保存、完成后隐藏恢复入口，以及记忆 warning/503 错误。
2. `node audit/frontend_regression.cjs`：上一轮回归仍通过（SSE 跨块 UTF-8、附件状态处理、Markdown 安全等）。
3. `npx tsc -b`：通过，原 23 项诊断降至 0；日志 `audit/alignment-typecheck.log`（成功时无输出）。
4. 最终生产构建与前端服务重启结果见本文件后续“最终运行状态”。

专项测试日志：`audit/alignment-frontend-regression.log`、`audit/alignment-original-regression.log`。回归使用真实组件与实际解析代码，外部 API 使用可控响应；真实后端与浏览器联调由主核对报告单独记录，不把 mock 测试冒充外部模型实测。

## 最终运行状态

补充：后端增加 `quality_review_status=unconfirmed` 后，前端已局部适配。审核事件中的 null/缺失/越界评分显示“质量审核待确认”，不显示 0 分或误判通过；`needs_revision` 优先于数值是否达到 7。最终报告及重载检查点均保留待确认说明。该分支已加入函数与 Chat 组件回归。

浏览器联调补修：主任务实际检索触发 Rerank 不可用降级后，后端 `rerank_score:null` 使原 `toFixed` 调用崩溃。现余弦与重排分数只在有限 number 时格式化；缺失余弦显示“不可用”，缺失重排分数不显示。增加真实 KnowledgeSearch 组件挂载与点击检索测试，覆盖 null、NaN、Infinity 及正常分数，已通过。修改后重新执行最终类型检查和生产构建。

浏览器布局补修：新增研究/记忆工具栏与消息原先是同一 flex row，工具栏被拉伸并挤占正文宽度。仅将聊天容器改为纵向、满宽排列，工具栏禁止伸缩、靠起点排列，保留自动换行和既有分屏尺寸；消息在工具栏下方占据完整可用宽度。视觉效果由主任务刷新后的真实浏览器复核，脚本测试不冒充布局验证。

记忆展示补修：`key_insights` 中 `_source_digest`、`_indexing_status`、`_has_more_messages`、`_source_message_ids`、`_source_message_offsets` 属于内部元数据。通用折叠面板现过滤所有以下划线开头的键，保留 topics、summary、key_insights、user_preferences 等业务字段，并为主题、洞察和偏好补中文标签；真实 MemoryPage 组件回归已验证内部消息 ID 与偏移不进入显示内容。

- 最终 `npm run build` 通过，耗时 2 分钟，4606 modules，包含质量审核、null 分数、工具栏布局与记忆内部字段过滤后的全部源码；JS 产物为 `index-D4NeXzBN.js`，CSS 为 `index-CmzgR0o7.css`，日志 `audit/alignment-frontend-build.log`。存在单 JS 文件超过 500 kB 的性能提示，构建成功；代码分包属于后续优化，不影响功能启动。
- 首轮联调前，已核对 PID 78310 的命令行、5183 监听及 `/proc/78310/cwd` 全部属于本项目，再仅重启该 Vite 进程，以 `npm run dev -- --strictPort --force` 启动并保留前端服务。最终两项补修已重新构建，主任务接到完成通知后负责再次精准重启并继续浏览器复测。
- 开发服务日志：`audit/alignment-frontend-dev.log`。开发服务端口为 5183。

主任务已完成最终浏览器复核，记录见 `audit/alignment-ui-final.md`：工具栏在正文上方紧凑排列，记忆页不显示内部键，公式、高亮、表格与真实检索结果可见。独立合成账号及其资源已全部清理，`audit/ui-fixture-cleanup.json` 已复核 PostgreSQL 各类记录、Milvus 记忆向量、知识库集合、Redis summary/index 队列均无残留；包含 UI 后续保存的 1 条记忆及 7 条向量。
