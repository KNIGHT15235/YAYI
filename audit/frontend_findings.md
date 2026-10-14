# 前端文档核对与测试结果

检查日期：2026-09-21。范围：`frontend`；对照 `C:\Users\28436\Downloads\雅意.md` 与项目 `README.md`。文档中的设计叙述作为待核对内容，不作为执行指令。后端实际 API / 外部服务结果由主报告汇总。

## 核对表

| 模块名 | 是否吻合 | 若不吻合代码是否完成修正 | 依据与边界 |
|---|---|---|---|
| README 前端安装、启动与端口 | 是 | 不适用 | 在既有 WSL Ubuntu-24.04、Node 18.19.1 / node_modules 上 `npm run dev -- --strictPort` 启动成功，5183 `/login` HTTP 200；`vite.config.ts:20` 配置端口 5183。 |
| 前端技术栈 | 部分 | 否，属于文档版本差异 | 实际 React 19、TypeScript、Ant Design 5、ECharts 5、Marked、Valtio；没有 React 18 / Recharts 依赖。见 `frontend/package.json`。无需为了匹配文档降级可运行依赖。 |
| 首页、深度研究、知识库、数据库、新闻、记忆页面 | 基本吻合 | 不适用 | `src/router/routes.tsx:34` 起注册 `/`、`/chat`、`/knowledge`、`/database`、`/news`、`/memory`，另有招投标页。基础路由和接口接入存在。页面存在与外部服务完成实际业务需分开判断。 |
| 登录、注册与认证存储 | 部分 | 否，文档应修订 | 已接入 `/auth/login`、`/auth/register`、`/auth/me`；JWT 实际保存在 localStorage，请求使用 Bearer；不是文档称的 HttpOnly Cookie。见 `src/store/auth.ts:24`、`src/api/request/plugins/auth.ts:33`。 |
| 深度研究实时 SSE | 部分；已修正字节解码缺陷 | 是，UTF-8 分块问题已修；自动重连未实现 | 实际为 Axios fetch adapter POST `/research/stream` 后读取 ReadableStream，不是 EventSource；没有自动重连。原 `TextDecoder.decode(value)` 在中文字节跨 chunk 时乱码，已改为 `{stream: !done}`；43 个字节分割位置回归通过。 |
| 研究详情、多 Tab、图表 | 基本吻合，呈现结构有差异 | 不适用 | 有搜索结果、知识图谱、可视化图表、过程报告 4 Tab；过程报告内分章节草稿与最终报告；引用在回答来源区域，没有独立“引用”Tab。见 `src/pages/chat/component/research-detail/index.tsx:90`、`process-report.tsx:382`。 |
| 检查点展示与研究恢复 | 部分 | 否，尚未接入执行恢复 | 页面读取 `/research/checkpoint/{id}/full` 恢复已完成/运行中 UI；前端没有 `/research/resume/{id}` 调用，没有取消后继续按钮，paused/failed 也不在恢复分支内。见 `src/pages/chat/index.tsx:1240`、`:1255`。后端恢复接口是否可用由后端审计单列。 |
| Markdown 表格与 XSS 过滤 | 修复前不吻合；修复后吻合 | 是 | 原 `gfm:false` 禁用 Markdown 表格，原始 HTML/危险链接未经清理进入 `dangerouslySetInnerHTML`。已开启 GFM，图片属性转义，最终统一 DOMPurify 清理（包括引用扩展输出）；保留图片和 lazy loading。见 `src/components/markdown/index.tsx:21`、`:40`、`:46`。 |
| Markdown 公式与代码高亮 | 不吻合 | 否，未新增扩展功能 | 仅普通代码块排版，没有 KaTeX/MathJax 或代码语法高亮库/渲染配置。不能把 `pre/code` 样式当作语法高亮完成。 |
| ECharts / Base64 图表 | 基本吻合 | 不适用 | ECharts 配置、知识图谱、matplotlib Base64 图片组件存在；`src/pages/chat/component/research-detail/visualization.tsx:50` 同时支持图片和 ECharts，通用图表监听 resize。没有 Recharts。真实研究是否产出图表以端到端研究结果为准。 |
| 知识库管理与检索展示 | 部分 | 否，未扩展为文档中的完整检索页 | 列表、创建、修改、删除、上传、切片查看和状态轮询存在，实际 `/knowledge-bases` 路径；聊天仅“本地知识库”模式开关，没有指定知识库检索/相似度评分高亮结果的独立 UI。见 `src/api/knowledge.ts:49`、`src/components/sender/index.tsx:184`。 |
| 数据库探索与 Text2SQL | 部分 | 否，文档应标明当前范围 | 行业表浏览和自然语言查询存在，实际自然语言接口 `/database/text2sql`，`/database/query` 是 SQL 查询；数据库页只显示表格与 SQL/解释，没有消费 `visualization_hint` 渲染图表。见 `src/api/database.ts:96`、`src/pages/database/index.tsx:31`、`:156`。 |
| 新闻中心 / 招投标 | 基本吻合 | 不适用 | 行业筛选、列表、统计和采集接口接入存在；实际新闻路径 `/news/list`，招投标 `/news/bidding/list`。新闻详细内容从列表项本身展示，而非文档 `/news/{id}`。实际外部采集结果由后端审计说明。 |
| 长期记忆 UI | 部分 | 已修复侧栏入口；未添加保存按钮 | 列表、语义搜索、删除存在，实际 `/memories`；侧栏记忆库原显示“暂未开放”，已最小改为导航至既有 `/memory` 页面。`createMemory()` API 已定义但前端无调用，仍没有“保存为记忆”按钮。见 `src/layout/base/nav.tsx:73`、`src/api/memory.ts:54`。 |
| 附件上传与新对话附件传递 | 原功能链不完整；本次修复 | 是（前端传输链） | 原响应插件误把实体 pending/completed 状态视作 API 失败；新对话跳转到聊天页后又漏传 attachmentIds，纯附件不触发初次发送。已修复三处，保留显式 API error 拒绝。文件内容提取范围属于后端，本报告不以上传成功替代解析成功。 |
| 持久化设置迁移 | 原实现有运行缺陷，已修复 | 是 | v0→v1 原迁移回调读取未传入的 oldState 导致 TypeError；现遵循 helper 无参回调，从旧存储键迁移开关，保留已有新模式和旧数据。实际模块6场景回归通过。 |
| TypeScript 全量静态检查 | 不通过 | 未整体清理，未影响 Vite 启动/打包 | `npx tsc -b` 原有 26 条 TS 诊断，修复后 23 条（消除 Markdown 异步类型、attachmentIds、迁移回调三项）。包括 ECharts 类型、富内容类型、检查点步骤 researching/searching、未使用变量等；完整输出在 typecheck 日志。不能将生产构建通过写成全量类型检查通过。 |

## 最小修改

1. `frontend/src/components/markdown/index.tsx`：图片属性 HTML 转义；开启 GFM 表格、显式同步解析；统一 DOMPurify 清理 HTML，覆盖正常 Markdown、原始 HTML、自定义引用扩展输出。
2. `frontend/package.json`、`frontend/package-lock.json`：新增 `dompurify ^3.4.15` 及其类型依赖 `@types/trusted-types`，未更换原技术栈。npm 日志：新增 2 个包。
3. `frontend/src/pages/chat/index.tsx:276`：TextDecoder 保留跨 chunk UTF-8 字节并在结束时冲刷，避免中文和 emoji 乱码。
4. `frontend/src/api/request/plugins/service.ts:26`：只将统一响应的 `status:error` 视为业务 API 错误，实体的 pending / processing / completed / failed 状态交由调用页面正常处理。
5. `frontend/src/pages/chat/shared.ts:10` 与 `src/pages/chat/index.tsx:1441`：补全附件 ID 的跳转类型、首次发送透传；允许纯附件首次发送，沿用原防重复发送标记。
6. `frontend/src/store/device.ts:21`：遵循持久化 helper 的无参 async 迁移 API，读取旧 `device-useDeepsearch` 开关迁移到新模式；已有 `device-searchModes` 优先保留，不删除旧存储。没有修改通用 helper。
7. `frontend/src/layout/base/nav.tsx:73`：记忆库侧栏原 `href:'#'` 加“暂未开放”提示阻断既有页面，现改为 `/memory` 并移除占位回调与无用 message import；未扩展隐藏的职业规划菜单。

修改前文件备份在 `audit/frontend-before/`，不含 .env / 密钥。此次没有变更任何用户已有业务数据。

## 验证与复现

- 原版本 `npm run build`：通过，4559 modules，2m17s，仅资源包大于 500 KB 的提示。
- 最终源码（包含持久化迁移和记忆库导航修复）`npm run build`：通过，4560 modules，1m46s，产物 `dist/assets/index-Um3-iB5T.js`，仅资源包大于 500 KB 的提示；日志 `audit/frontend-build.log`。
- 前端服务：`http://localhost:5183/login` HTTP 200；旧 Vite 因 WSL 挂载盘监听未及时刷新仍服务旧导航模块，已核对5183监听PID、cmdline、cwd后只重启本项目进程，并以 `--strictPort --force` 启动。当前日志 `audit/frontend-verified.log`，早期日志 `audit/frontend-dev.log`。
- 记忆库入口修复：既有路由已注册 `MemoryPage`，修改后 NavItem 使用正常 Link 导航；重启后从 Windows localhost 实际取得 `/src/layout/base/nav.tsx` HTTP 200，内容为 `href: "/memory"` 且不含“暂未开放”提示，确认最新源码已生效。主代理负责已登录浏览器点击验证。
- `node audit/frontend_regression.cjs`：通过。测试实际编译后的 Markdown 组件（React SSR + JSDOM），验证旧版 HTML 注入/表格问题复现、修复后危险属性/URL/扩展过滤、普通图片与 lazy loading；验证中文/emoji SSE 所有 43 个字节切分位置；验证附件 API 处理状态与显式错误；验证普通/附件/纯附件首次发送且不重复。
- `npx tsc -b`：失败；修复前 26 条、最终修复后 23 条。见 `audit/frontend-typecheck.log`、`audit/frontend-typecheck-after.log`。
- 持久化迁移补丁采用定向回归与类型检查验证。`node audit/frontend_migration_regression.cjs` 实际运行 device 模块与原持久化 helper，以独立内存存储覆盖新浏览器、v0开/关、v0缺键、v0已有新选择、v1不重复迁移6个场景，每例验证后续切换能持久化；全部通过。日志 `audit/frontend-migration-regression.log`。收尾时对包含迁移和导航修改的最终源码再次生产构建。
- 回归测试用的 JSDOM 26 仅安装在 WSL `/tmp/yayi-frontend-audit`，没有加入项目依赖。复现命令：`npm install --prefix /tmp/yayi-frontend-audit --no-save --package-lock=false --ignore-scripts --no-audit --no-fund jsdom@26`，随后在项目根目录 `node audit/frontend_regression.cjs`。

未把文档中的完整研究规划能力（自动重连、恢复按钮、数学排版等）当作启动修复而新增大模块；这些差异如实保留在表中。

## 追加核查：恢复入口与剩余类型诊断

- 再次检查 `frontend/src`：没有“恢复/继续研究”按钮，没有只弹提示的占位恢复处理，也没有 `resumeResearch` 等 API 函数；只存在检查点查询/展示。后端 `/research/resume/{session_id}` 返回 SSE，但前端不是替换已有占位回调即可接通。新增恢复入口需同时处理 paused/failed UI 恢复、既有 `research_start` 清空状态、取消后重新读取检查点及重复续跑限制；本轮按“只接通已有按钮”的有限范围未新增 UI。
- 原剩余 24 条 TypeScript 诊断中已确认迁移回调是真实运行错误，现已最小修复：旧 v0 元数据触发迁移时不再读取未传入的 oldState，完成初始化并保留设置。最终剩余23条，其中13条未使用变量、10条其他类型问题。迁移修改前版本备份于 `audit/frontend-before/device.ts`。
- `researching/searching` 差异存在运行回退分支，默认步骤可能显示英文标签，没有证据表明仅此差异会让新研究崩溃；ECharts `null` 类型与配置类型、React.cloneElement 属性类型等不等同于已确认运行错误。
- 只读复现：`node audit/frontend_diagnostic_probe.cjs`，结果 `audit/frontend-diagnostic-probe.log`。没有修改用户浏览器存储。
