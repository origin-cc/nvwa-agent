# NvwaAgent（女娲）

> **NvwaAgent — Snapshot-Driven Everything-is-Plugin Full-Stack AI Agent Platform**

Nvwa (女娲): Chinese mythological goddess who shapes creatures from clay.
NvwaAgent assembles custom agents out of hot-pluggable backend agents/tools and React UI plugins.
Architecture reference: DeepSeek-Harness https://github.com/deepseek-ai/deepseek-harness

一款**完全本地化部署、全链路插件化、高解耦可扩展的 Web 通用 AI 智能体开源系统**。借鉴 DeepSeek-Harness「一切皆插件」架构思想，不仅后端智能体、工具可插拔，**前端 React 页面与组件同样支持插件化热插拔**。系统不固化任何业务形态，「个人助手」「工作助手」等均只是前后端插件自由组合的效果示例。

> **状态：v0.1-alpha（早期预览版，面向开发者原型验证）**

---

## 核心特性

- **全栈插件化**：后端 Agent、工具与前端 React 页面、组件全部为可插拔插件，具备「加载→激活→运行→禁用→卸载→资源回收」完整生命周期。
- **前后端联动**：后端插件启用/禁用自动触发对应前端 UI 插件的加载/卸载、挂载/销毁，状态强一致。
- **插件快照**：一键保存/加载/导入/导出前后端插件组合快照，自由切换任意场景形态。
- **全程本地私有化**：基于 vLLM 本地推理、FAISS 向量检索、SQLite 存储，无云端依赖、无数据外泄。
- **全流程可观测**：任务执行、插件调度、工具调用全链路 SSE 实时推送，会话事件日志仅追加、可回放审计。
- **模拟调试模式**：`mock_mode_enabled=true` 时绕过 vLLM，无需 GPU 即可验证插件框架、任务链路与前端联动。

## 架构

六层全解耦架构：前端 React UI 插件运行层 → Web 交互适配层 → 通信服务层（FastAPI + SSE）→ 后端插件运行内核层（PluginRuntime + 核心调度器）→ 工具资源层 → 底层依赖层（vLLM / FAISS / SQLite / 文件存储）。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | React 18 + Ant Design + Vite + 自定义 React UI 插件运行时 |
| 后端 | FastAPI + LangGraph + 自定义 PluginRuntime 插件运行时 |
| 推理 | vLLM（本地离线） |
| 向量化 | sentence-transformers（本地 Embedding，与 vLLM 解耦） |
| 检索引擎 | FAISS（本地轻量向量库） |
| 存储 | SQLite（本地文件数据库） |
| 通信 | SSE 长连接 |

## 快速开始

> 完整部署步骤见 [dev-doc/NvwaAgent-需求PRD.md](./dev-doc/NvwaAgent-需求PRD.md) 与 [dev-doc/NvwaAgent‑详细设计.md](./dev-doc/NvwaAgent‑详细设计.md)。

### 环境要求

- 后端：Python 3.10–3.12
- 前端：Node.js（Vite 构建）
- 浏览器：Chrome / Edge 最新版

### 安装与启动

```bash
# 1. 后端依赖（安装到 backend/.deps，见 backend/requirements.txt）
cd backend
pip install -r requirements.txt --target .deps

# 2. 启动后端（FastAPI，http://127.0.0.1:8000）
$env:PYTHONPATH="$PWD\.deps"   # Windows PowerShell；Linux/macOS: export PYTHONPATH=$PWD/.deps
python -m uvicorn nvwa_agent.app:create_app --factory --host 127.0.0.1 --port 8000

# 3. 启动前端（另开终端，Vite dev server）
cd frontend
npm install
npm run dev
```

首次启动自动建表（SQLite `data/nvwa_agent.db`）、初始化默认配置并扫描 `plugins/` 目录。

### 推理后端切换（system_config）

| 配置 | 说明 |
| --- | --- |
| `llm_provider=mock` 或 `mock_mode_enabled=true` | 模拟推理，无 GPU 调试插件框架与任务链路 |
| `llm_provider=api` | OpenAI 兼容接口（如 DeepSeek），配置 `api_base_url` / `api_key` / `api_model` |
| `llm_provider=vllm` | 本地 vLLM（配置 `vllm_model_path`） |

### 运行测试

```bash
cd backend
$env:PYTHONPATH="$PWD\.deps"; python -m pytest tests -q   # 42 个用例，临时库隔离、无网络请求
```

## 插件开发

前后端插件统一遵循 `plugin.json` 元数据规范，放入 `./plugins/` 目录，系统扫描后即可识别。

**完整的插件开发规范（plugin.json 字段、后端 SDK 代码契约、UI 插件导出契约、SSE 事件契约、示例说明）见 [dev-doc/NvwaAgent-插件开发指南.md](./dev-doc/NvwaAgent-插件开发指南.md)。**

- 后端插件类型：`backend_agent` / `backend_tool`
- 前端插件类型：`ui_page_plugin` / `ui_component_plugin`

插件目录示例：

```
plugins/
├── demo-agent-plugin/
│   ├── plugin.json
│   └── main.py
└── demo-ui-chat/
    ├── plugin.json
    └── dist/
        └── index.js
```

## 文档

- [dev-doc/NvwaAgent-需求PRD.md](./dev-doc/NvwaAgent-需求PRD.md) — 产品需求（做什么）
- [dev-doc/NvwaAgent‑详细设计.md](./dev-doc/NvwaAgent‑详细设计.md) — 工程详细设计（如何实现）
- [dev-doc/NvwaAgent-实施计划.md](./dev-doc/NvwaAgent-实施计划.md) — 里程碑实施计划
- [dev-doc/NvwaAgent-插件开发指南.md](./dev-doc/NvwaAgent-插件开发指南.md) — 插件开发者文档（plugin.json / SDK / SSE 契约）

## 项目边界（不做什么）

- ❌ 不实现多用户、多租户、账号登录系统（单机单用户）
- ❌ 不实现云端托管、官方在线插件市场（插件仅本地文件导入）
- ❌ 不将公有大模型 API 作为强制依赖（优先 vLLM 本地推理）
- ❌ 不内置图形化插件 IDE
- ❌ 不支持分布式多机器部署

---

> 本项目定位单机本地私有化部署、单用户使用。第三方插件请自行审计安全，谨慎加载不受信任来源的插件。
