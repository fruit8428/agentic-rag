"""
聊天 API 速率限制（每社每分鐘 N 次，N 由 CHAT_RATE_LIMIT_PER_MINUTE 決定，預設 10）。

用記憶體計數的滑動視窗。Vercel 無狀態部署時，每個執行個體各自計數，
所以實際上限可能略高於 N，但足以擋住誤觸或惡意連打，又不需要額外資料表。
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.config import settings

_WINDOW_SECONDS = 60
_lock = threading.Lock()
_hits: dict[str, deque] = defaultdict(deque)


def check_rate_limit(key: str) -> tuple[bool, int]:
    """
    記錄一次呼叫並回傳 (是否允許, 幾秒後可再試)。
    key 建議用 club_id；沒有社（例如管理員）就用 user_id。
    """
    limit = settings.CHAT_RATE_LIMIT_PER_MINUTE
    if limit <= 0:  # 0 或負數＝關閉限制
        return True, 0
    now = time.time()
    with _lock:
        q = _hits[key]
        while q and now - q[0] >= _WINDOW_SECONDS:
            q.popleft()
        if len(q) >= limit:
            retry_after = int(_WINDOW_SECONDS - (now - q[0])) + 1
            return False, max(retry_after, 1)
        q.append(now)
        return True, 0


def reset_rate_limits() -> None:
    """測試用：清空計數。"""
    with _lock:
        _hits.clear()
