import sys
from pathlib import Path

# 將 backend 目錄加入 Python 模組搜尋路徑，讓 Vercel Serverless Function 可直接載入 FastAPI app
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import app  # noqa: E402, F401
