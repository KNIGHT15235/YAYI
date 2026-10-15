# YAYI 科研助手后端

FastAPI 提供登录、知识库、文献解析与科研任务接口；六角色 asyncio 执行器负责检索、分析、写作、审核和图表生成。整体流程及本次真实验证结果见 [项目说明](../README.md) 和 [验收报告](../docs/WSL真实全链路验收报告-2026-10-14.md)。

## 环境准备

在 WSL 的独立 Python 环境中操作。本次验证使用 Python 3.10.21；不要将依赖直接安装进系统或 base 环境。

```bash
cd backend
python -m pip install -r requirements.txt
```

首次配置时将 `.env.example` 复制为 `.env`，已有文件不要覆盖。配置自己的：

- PostgreSQL、Redis、Milvus 连接参数与独立数据库。
- 模型服务凭据，例如 `DASHSCOPE_API_KEY`，以及账户可用的模型名称。
- DocMind 的 `DOCMIND_ACCESS_KEY_ID`、`DOCMIND_ACCESS_KEY_SECRET`。
- 应用端口、登录鉴权配置和前端允许访问的 origin。

完整变量以 `.env.example` 和代码读取配置为准。凭据仅保存在本地，不提交到仓库。准备基础服务时检查 Compose 的容器名、端口和数据卷；已有实例应复用或隔离，不能为启动本项目删除旧数据。

## 本机已验证的启动方式

```bash
cd /mnt/d/ldj/01/YAYI_0929/backend
DEFAULT_MODEL=qwen-plus NEWS_COLLECTION_ENABLED=false MEMORY_AUTO_ENABLED=false \
  /home/ldj/anaconda3/envs/yayi_b/bin/python app/app_main.py
```

本机 `APP_PORT=8029`，接口文档为 http://localhost:8029/docs，存活检查为 http://localhost:8029/hello。其他机器按实际路径、环境和端口替换；默认值不代表本机覆盖配置。此启动方式修改代码后需要重启。

模型选择顺序：角色 `*_MODEL` > `DEFAULT_MODEL` > 保存的研究配置/默认值。恢复任务会记录实际使用的模型；不会因请求失败暗中切换供应商。

## 科研链路与接口验证

1. 通过前端登录并创建知识库，上传测试文献。
2. 等待 DocMind 解析、资产/片段持久化、embedding 和 Milvus 索引完成。
3. 发起 `profile_id=science` 的科研任务，绑定当前用户有权访问的知识库。
4. 检查写前分析补检、审核后的修订分支、SSE事件、引用身份和版本。
5. 停止并恢复，确认 checkpoint 与消耗预算保留；新任务使用新会话。

API 需要相应登录身份与资源权限，请通过 `/docs` 查看当前请求模型，不沿用旧版匿名调用示例。已有研究的会话再次启动返回409，恢复与追加复核使用专用入口，不直接覆盖检查点。

真实验收脚本位于 `audit/`。只读连接检查：

```bash
cd /mnt/d/ldj/01/YAYI_0929
/home/ldj/anaconda3/envs/yayi_b/bin/python audit/live_acceptance.py preflight
```

离线回归的完整22模块命令及审核/人工状态复验见 [最新复验报告](../docs/审核质量与人工状态复验报告-2026-10-15.md)，真实上传/研究操作与故障注入边界见 [全链路报告](../docs/WSL真实全链路验收报告-2026-10-14.md)。真实服务测试会创建独立测试数据，并可能产生模型、解析和向量服务费用；不要把运行快照、测试账号密码或令牌提交到Git。
