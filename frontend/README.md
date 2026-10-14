# yayi 雅意 — 科研助手前端

## 快速开始

### 环境要求
- Node.js >= 18
- npm >= 9

### 安装与运行

```bash
# 1. 安装依赖
npm install --legacy-peer-deps

# 2. 启动开发服务器
npm run dev
```

启动成功后访问前端登录入口 http://localhost:5199/login（固定端口；冲突时先停止占用服务）。

### 常见问题

#### macOS/Linux 权限问题

如果遇到 `Permission denied` 错误，运行：

```bash
chmod +x node_modules/.bin/*
```

然后重新执行 `npm run dev`

#### 当前 Windows / WSL 环境

在 WSL Ubuntu-24.04 中进入 `/mnt/d/ldj/01/YAYI_0929/frontend` 后运行命令。开发服务器通过 `/api` 代理到 `http://127.0.0.1:8029`。`npm run dev`、`build` 和 `preview` 直接调用已安装 Vite 的 Node 入口，兼容复制目录后 `.bin` 链接缺失的情况。

---

## 技术栈

- React 19
- TypeScript
- Vite
- Ant Design 5
- React Router 6

## 可用命令

| 命令 | 说明 |
|------|------|
| `npm run dev` | 启动开发服务器 |
| `npm run build` | 构建生产版本 |
| `npm run preview` | 预览生产版本 |
| `npm run lint` | 运行代码检查 |


## 科研入口与验证

默认 `VITE_RESEARCH_PROFILE=science`，保留行业功能代码，通过配置切换；科研入口显示新的研究、研究历史、记忆库和知识库。展示问题：

> 围绕2020-2026年光学遥感图像变化检测方法开展文献调研，生成文献综述。

右侧展示搜索结果、文献库、假设与审核、知识图谱、可视化图表与过程报告。来源核对标签只表示文献身份或元数据已核对；逐声明的支持关系与未核验项在“假设与审核”中单独展示。位置字段只展示后端实际解析值。

```bash
npm run typecheck
node --test audit/research-contract.test.mjs
npm run build
```

历史恢复同时兼容旧引用字段、新科研元数据及服务端 checkpoint。生产环境部署须将 `/api` 反向代理到后端。
