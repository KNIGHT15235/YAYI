# YAYI 雅意 · AI-Scientist 科研助手

仓库保存源码、配置示例、验证脚本和说明文档，不包含本机 `.env`、上传文献、解析资产、运行快照、日志或依赖目录。首次配置请复制 `backend/.env.example` 为 `backend/.env` 并填写自己的凭据；已有本地配置不要覆盖。`start-services.sh` 从该环境文件读取数据库密码，示例中的占位密码需自行替换。下文的演示历史与运行结果属于本机数据，不会随克隆自动出现。

此目录是 `D:\ldj\01\source\industry_information_assistant` 的独立副本。复用原有六 Agent、FastAPI、React、DocMind、Milvus、PostgreSQL、Redis、SSE 和 checkpoint，新增科研配置、真实文献采集、证据及声明核验、文献资产定位和科研展示页面。

## 本机运行

已配置 WSL Ubuntu-24.04 的 `yayi_b` 环境，无需重新安装。保留当前 `backend/.env`，其中包含用户原有 API 配置。基础容器复用原项目正在运行的实例，数据使用独立数据库。

| 项目 | 当前配置 |
|---|---|
| 网页 | http://localhost:5199 |
| 后端 / 接口文档 | http://localhost:8029/docs |
| Python | `/home/ldj/anaconda3/envs/yayi_b/bin/python` |
| PostgreSQL | `localhost:15432`，数据库 `yayi_0929` |
| Redis | `localhost:16379`，DB `9` |
| Milvus | `localhost:29530`，数据库 `yayi_0929` |

两个 WSL 终端分别执行：

```bash
cd /mnt/d/ldj/01/YAYI_0929
bash run-yayi.sh backend
```

```bash
cd /mnt/d/ldj/01/YAYI_0929
bash run-yayi.sh frontend
```

若地址已能访问，直接打开网页即可，无需重复启动。后端代码修改后重启后端；前端已开启 WSL 文件轮询。`bash run-yayi.sh status` 查看存活状态。基础容器停止时，在原项目目录运行 `./start-services.sh start`；副本内保留的 Compose 文件属于复制过来的基础服务配置，不应与原项目重复启动相同容器。

初始化新数据库时才执行（本机已经完成）：

```bash
/home/ldj/anaconda3/envs/yayi_b/bin/python audit/bootstrap_yayi.py
```

## 展示

展示账户：`yayi_demo`。本机密码保存在 `backend/storage/demo-access.json`，该文件只用于本机登录，不应提交或分享。进入“研究历史”打开 **2020—2026光学遥感变化检测文献综述**。其精确查询为：

> 围绕2020-2026年光学遥感图像变化检测方法开展文献调研，生成文献综述。

研究包含真实文献集合、提出和核验的假设、知识图谱、可复算的文献分布图、综述、引用及逐段核验记录。知识库 **遥感变化检测论文** 保存 BIT 论文原件、可定位文本和提取的图表资产。

以同样条件重新执行完整测试（会调用已配置的模型和向量服务，并新建历史）：

```bash
/home/ldj/anaconda3/envs/yayi_b/bin/python -u audit/run_science_demo.py --kb 遥感变化检测论文
```

公开文献来源为 Crossref 注册元数据及 arXiv 作者摘要，按日期、题名、主题过滤并去重。`verified` 表示来源身份已核对；内容声明另行审核。文献分布图反映本次检索样本，方法关键词可以多标签计数，不代表整个领域的论文总量或性能排名。

## 实施与验收资料

- [实施版项目文档](docs/雅意原型-实施版.md)
- [代码修改方案与实施映射](docs/雅意原型-代码修改方案.md)
- [本次测试和输出审核](audit/YAYI_0929验收报告.md)
- [生成的综述](audit/demo-report.md)
- 本机运行记录与历史编号：`audit/demo-run-summary.json`（不随仓库上传）
- 本机120篇文献来源复核：`audit/demo-literature-source-audit.json`（不随仓库上传）
- [正文与假设的独立内容审核](audit/content-review-final.md)
- 本机真实 PDF 资产及检索测试：`audit/science-assets-live.json`（不随仓库上传）
- [数据库探索与科研资讯演示操作](docs/数据库探索与科研资讯演示操作.md)

`audit/demo-events.jsonl` 是原始 SSE，`demo-result.json` 是最终结构化结果，`demo-checkpoint.json` 和 `demo-history.json` 用于核对持久化恢复。审计数据不包含登录 token。项目中保留的旧核对报告描述复制前版本，以本次实施文档和验收报告为准。

## 常用验证

```bash
cd /mnt/d/ldj/01/YAYI_0929
/home/ldj/anaconda3/envs/yayi_b/bin/python audit/test_science_engine.py
/home/ldj/anaconda3/envs/yayi_b/bin/python audit/test_science_assets.py
cd frontend
npm run typecheck
npm run build
```

网页包含独立首页、深度研究、研究历史、记忆库、知识库管理、数据库探索与科研资讯。“深度研究”页可直接切换 **科研背景调研 / 行业调研**：科研发送 `profile_id=science`，行业发送 `profile_id=industry`；历史及恢复沿用原会话模式。

科研路径中 Analyze 只分析证据、假设与缺口，Review 统一决定补检。补检后重新 Analyze、更新图谱和图表，再修订原报告。Scout 的初次检索及审核授权补检均支持有界递归，默认深度 2、分支 2、额外递归查询 8；预算及队列随检查点保存。详见 [实施方案](docs/科研补检与递归深挖调整方案.md) 和 [本轮验证](audit/科研补检与模式切换验证.md)。

定时行业资讯采集通过 `NEWS_COLLECTION_ENABLED=false` 关闭，研究与记忆任务继续使用独立状态。
