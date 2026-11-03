"""模組 10：社共用帳號 — 每個社對應一個 Supabase Auth 帳號（合成 Email），社密碼由 Supabase Auth 保管。"""
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from supabase import Client, create_client

from app.config import settings

# 社帳號的合成 Email 網域（使用者永遠看不到，只是 Supabase Auth 需要一個唯一 Email）
CLUB_EMAIL_DOMAIN = "clubs.3523.local"
# 啟用碼字元集：排除 0/O/1/I 等容易看錯的字
_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

MIN_PASSWORD_LENGTH = 6


def club_login_email(club_id: str) -> str:
    return f"club-{club_id}@{CLUB_EMAIL_DOMAIN}"


def generate_activation_code() -> str:
    """產生 XXXX-XXXX 格式的一次性啟用碼。"""
    raw = "".join(secrets.choice(_CODE_CHARS) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def normalize_code(code: str) -> str:
    """使用者輸入的啟用碼：去空白、轉大寫、補上連字號，避免因格式小差異而失敗。"""
    cleaned = "".join(ch for ch in (code or "").upper() if ch.isalnum())
    return f"{cleaned[:4]}-{cleaned[4:]}" if len(cleaned) == 8 else cleaned


def validate_new_password(plain: str) -> None:
    if len(plain or "") < MIN_PASSWORD_LENGTH:
        raise ValueError(f"社密碼至少需要 {MIN_PASSWORD_LENGTH} 個字元")


def sign_in(email: str, password: str) -> Optional[dict]:
    """用 Supabase Auth 驗證帳密；成功回傳 session 資訊，密碼錯誤回傳 None。每次使用新的 client 避免狀態互相污染。"""
    client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
    try:
        res = client.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as e:
        if "Invalid login credentials" in str(e):
            return None
        raise
    if not res or not res.session:
        return None
    s = res.session
    return {
        "access_token": s.access_token,
        "refresh_token": s.refresh_token,
        "expires_in": s.expires_in,
        "token_type": s.token_type or "bearer",
        "user_id": res.user.id if res.user else None,
    }


def create_club_account(admin: Client, club: dict, password: str) -> str:
    """為社建立 Auth 帳號並把 profiles 綁到該社；回傳新帳號 id。"""
    email = club_login_email(club["id"])
    created = admin.auth.admin.create_user({
        "email": email,
        "password": password,
        "email_confirm": True,
        "user_metadata": {"club_id": club["id"], "club_name": club["name"], "kind": "club"},
    })
    if not created or not created.user:
        raise RuntimeError("建立社帳號失敗")
    user_id = created.user.id
    now = datetime.now(timezone.utc).isoformat()
    # 觸發器可能已建立 profiles 列，這裡用 upsert 保證綁定社別
    admin.table("profiles").upsert(
        {"user_id": user_id, "club_id": club["id"], "role": "member", "joined_at": now},
        on_conflict="user_id",
    ).execute()
    admin.table("clubs").update(
        {"auth_user_id": user_id, "activated_at": now, "activation_code": None}
    ).eq("id", club["id"]).execute()
    return user_id


def set_account_password(admin: Client, user_id: str, new_password: str) -> None:
    admin.auth.admin.update_user_by_id(user_id, {"password": new_password})


def delete_account(admin: Client, user_id: str) -> None:
    try:
        admin.auth.admin.delete_user(user_id)
    except Exception as e:
        if "not found" not in str(e).lower():
            raise


# ----------------------------------------------------------------------------
# 登入失敗節流（記憶體版：同一個鍵 10 分鐘內失敗 8 次就暫時鎖住）
# 在 Vercel 無伺服器環境中每個執行個體各自計數，仍能擋掉最粗暴的暴力嘗試。
# ----------------------------------------------------------------------------
_FAIL_WINDOW_SECONDS = 600
_FAIL_LIMIT = 8
_failures: dict[str, list[float]] = {}


def check_throttle(key: str) -> None:
    now = time.time()
    recent = [t for t in _failures.get(key, []) if now - t < _FAIL_WINDOW_SECONDS]
    _failures[key] = recent
    if len(recent) >= _FAIL_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="密碼錯誤次數過多，請 10 分鐘後再試，或聯絡地區管理員重設密碼",
        )


def record_failure(key: str) -> None:
    _failures.setdefault(key, []).append(time.time())


def clear_failures(key: str) -> None:
    _failures.pop(key, None)
