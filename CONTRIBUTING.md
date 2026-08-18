# 贡献指南（CONTRIBUTING）

> NvwaAgent 是「一切皆插件」的全栈 AI Agent 平台。欢迎贡献插件、文档与测试。

## 1. 开发环境

- Python 3.10–3.12（依赖安装于 `backend/.deps`）
- Node.js 18+（前端 Vite）
- 数据库：SQLite（自动建表，无需手动初始化）

```bash
# 后端依赖（首次）
pip install -r backend/requirements.txt -t backend/.deps

# 前端依赖
cd frontend && npm install

# 一键启动（详见 start.ps1 / start.bat）
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

## 2. 分支与提交规范

- 主分支 `main`；功能开发使用 `feat/xxx`、修复使用 `fix/xxx` 分支
- 提交信息遵循：`<type> <scope> <简述>`（如 `feat(plugin) 新增文件写入工具`、`fix(runtime) 修复任务上下文继承`）
- 每个里程碑（M 阶段）完成后做一次 checkpoint 提交

## 3. 测试规范

```bash
cd backend
# Windows（依赖在 backend/.deps）
$env:PYTHONPATH="$PWD\.deps"; python -m pytest tests -q
```

- 所有测试使用临时数据库隔离，不触碰真实数据、不发起网络请求
- 新增功能需补充对应单测；核心插件运行时（`core/plugin_runtime`、`core/scheduler`、`core/knowledge`）行覆盖目标 ≥ 70%
- 提交前确保 `pytest` 全绿

## 4. 插件开发流程

1. 在 `plugins/` 下新建插件目录（目录名 = 插件 id）
2. 编写 `plugin.json` 与入口（后端 `main.py` / 前端 `index.js`）
3. 遵循《NvwaAgent-插件开发指南.md》中的 SDK 契约、UI 导出契约、SSE 事件契约
4. `POST /api/v1/plugins/scan` 扫描，验证无 `fault`
5. mock 模式（`llm_provider=mock`）联调端到端链路
6. 提交插件 + 对应测试

## 5. 文档与契约

- REST API 参考：`dev-doc/NvwaAgent-REST-API.md`
- 插件开发指南：`dev-doc/NvwaAgent-插件开发指南.md`
- 需求/设计/实施计划：`dev-doc/`（PRD、详细设计、实施计划按版本目录组织）
