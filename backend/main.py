import sys
from pathlib import Path

# 確保 backend 目錄在 sys.path 中，相容 Vercel Services 與本地執行
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import app  # noqa: E402, F401
