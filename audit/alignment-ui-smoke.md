# 最终前端浏览器冒烟记录

> 此文件保留子任务早期浏览器不可用的记录。主任务随后完成真实页面验证，最终结果请见[alignment-ui-final.md](alignment-ui-final.md)。

日期：2026-09-21。目标：对本轮补齐后的 `http://localhost:5183` 做真实浏览器抽查，并区分已有脚本验证与实际浏览器验证。

## 当前执行环境的限制

已阅读 `computer-use/SKILL.md` 及其 guidance、confirmations。通过可用的 `cua_repl` 浏览器接口尝试新开独立测试页：

```text
cua.createBrowserTab("iab", "http://localhost:5183", { visible: true })
→ Browser is not available: iab

cua.getState()
→ {"apps":[],"browsers":[]}
```

因此，本子任务未获得可控制的浏览器或应用。当前工具还明确标记 native computer APIs disabled；未用其他脚本、DevTools、自动化框架或截图方式绕过该限制。已向主核对任务反馈；主任务可在其自身可用的浏览器环境继续抽查。

上述初次浏览器尝试没有创建测试账号、写入测试数据或打开成功的浏览器页。下表只说明该阶段已有脚本和服务验证，不能替代本轮新增功能的真实浏览器验证。后续主任务恢复浏览器能力后，已要求建立独立 fixture，见文末补充。

## 覆盖区分

| 关键功能 | 已有脚本/服务验证 | 本次真实浏览器状态 | 浏览器补查要点 |
|---|---|---|---|
| 前端启动 | 最终生产构建成功；Vite 已强制刷新启动，5183 HTTP 200 | 未打开成功 | 登录页与首页是否正常加载、无白屏 |
| 知识库检索入口与结果 | 安全文本高亮组件回归通过；搜索 API 与页面已接通；后端端到端检索由主报告记录 | 未检查 | 选择知识库，看到检索框；实际结果显示文档名、段落、相似度、重排状态和警告 |
| 原文件下载 | 前端 helper 已验证 Bearer、Blob 和 404 需重传错误；文档列表与结果均接入下载按钮 | 未检查 | 真实文件按钮可下载；历史缺失文件禁用并说明需重新上传 |
| 保存为记忆 | 真实 Chat 组件加载测试，通过点击调用 API，验证成功 warning 与真实 503 detail 呈现 | 未检查 | 登录自己的测试会话，看到“保存为记忆”；点击后的结果与后端状态一致 |
| 研究恢复 | 真实 Chat 组件加载测试，暂停检查点先 full 恢复再读取分块 SSE；旧来源保留、图表去重、最终消息保存、完成后入口隐藏均通过 | 未检查 | 暂停会话显示“继续研究”；已有草稿/来源恢复；完成会话不继续显示恢复按钮 |
| Markdown 代码与公式 | 实际渲染器回归通过 highlight.js、KaTeX 行内/块公式、MathML、SVG/HTML XSS 清洗、图片懒加载与代码转义 | 未检查 | 浏览器中代码着色与公式排版、长公式横向滚动、图片样式是否正常 |
| SQL 数据图表 | 实际配置构建回归通过 bar/line/pie/scatter、数值字符串、null、缺数据保留表格 | 未检查 | 数据库查询结果能实际看到 ECharts 画布，尺寸与表格协调 |
| 报告内图表 | 实际解析器回归通过 chart_id 精确匹配、重复占位符去重、真实图片链接保留 | 未检查 | 过程报告中 ECharts/Base64 图表在正确位置出现 |
| TypeScript | `npx tsc -b` exit 0，0 项诊断 | 不适用 | — |

## 已有证据

- `audit/alignment_frontend.md`：实现范围、文档具体行号与替换文字。
- `audit/alignment-frontend-regression.log`：9 组专项脚本回归通过（后续增加质量审核待确认状态、知识库 null/非有限评分、记忆内部字段过滤组件测试）。
- `audit/alignment-original-regression.log`：上一轮专项回归仍通过。
- `audit/alignment-typecheck.log`：类型检查成功，无诊断输出。
- `audit/alignment-frontend-build.log`：最终 4606 modules，2 分钟，构建成功；仅有大 chunk 性能提示。
- `audit/alignment-frontend-dev.log`：最终 Vite `--strictPort --force` 服务已保留，端口 5183。

若主任务随后完成真实浏览器验证，应在主报告补充其实际观察；不要将此文件的脚本通过改写为浏览器通过。

## 后续合成数据准备

主任务随后确认其 CUA 已可用，授权为其实际 UI 操作提供一次性合成数据。`audit/ui_fixture.py setup` 已通过真实 HTTP 注册独立随机账号，创建自己的知识库与一份“UI冒烟_紫藤73.txt”，状态为 completed，原文件可下载；通过会话消息 API 保存公式、代码、表格，并仅在该账号下创建暂停检查点及合成图表用于查看恢复入口。

此 fixture 不调用研究/聊天大模型，仅为该单段 TXT 做真实向量化。暂停检查点是 UI 展示 fixture，不能用于验证实际研究续跑。元数据 `audit/ui-fixture-metadata.json` 只含合成账号名、资源 ID 和状态，不含密码或 Token。临时登录信息已单独提供主任务，待主任务通知后执行 `audit/ui_fixture.py cleanup`，按精确 UUID 与生成账号名清理该 fixture。真实 UI 操作及结果由主任务记录。

最终补记：主任务完成浏览器复测并退出、关闭测试页后，已执行 cleanup。UI 另行保存的 1 条记忆和 7 条向量也已清理；`audit/ui-fixture-cleanup.json` 确認 PostgreSQL、Milvus、Redis 范围内该 fixture 无残留。最终真实 UI 记录见 `audit/alignment-ui-final.md`，本文件保留最初环境不可用的历史事实。
