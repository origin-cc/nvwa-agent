"""启动入口：cd backend && python main.py（或 uvicorn main:app --port 8000）。

自动挂载项目内 .deps 依赖目录（沙箱环境下 pip --target 安装的依赖）。
"""
import sys
from pathlib import Path

_deps = Path(__file__).resolve().parent / ".deps"
if _deps.exists() and str(_deps) not in sys.path:
    sys.path.insert(0, str(_deps))

import uvicorn  # noqa: E402

from nvwa_agent.app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
