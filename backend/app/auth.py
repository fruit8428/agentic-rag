from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client, create_client

from app.config import settings

security = HTTPBearer()


@dataclass
class AuthenticatedUser:
    id: str
    email: str
    access_token: str
    supabase: Client
    # 模組 9：所屬社與角色（來自 profiles 表）
    club_id: Optional[str] = None
    club_name: Optional[str] = None
    role: str = "member"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def get_admin_supabase() -> Client:
    """回傳具備 Service Role 權限的 Supabase Client（僅用於系統管理操作，會繞過 RLS，使用時必須自行套用可見性規則）。"""
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def get_user_supabase(access_token: str) -> Client:
    """
    回傳綁定當前使用者 JWT 的 Supabase Client。
    所有透過此 Client 進行的資料庫查詢都會觸發 Postgres 行級安全性 (RLS)。
    """
    client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
    client.postgrest.auth(access_token)
    return client


def load_profile(admin_supabase: Client, user_id: str, email: str) -> dict:
    """
    讀取使用者的 profiles 列（所屬社、角色）。找不到就建立一列。
    若 email 等於設定檔的 ADMIN_EMAIL 但角色不是 admin，自動補正（首次啟動自我修復）。
    """
    res = (
        admin_supabase.table("profiles")
        .select("user_id, club_id, role, clubs(name)")
        .eq("user_id", user_id)
        .execute()
    )
    profile = res.data[0] if res.data else None
    if profile is None:
        ins = admin_supabase.table("profiles").insert({"user_id": user_id}).execute()
        profile = (ins.data[0] if ins.data else {"user_id": user_id, "club_id": None, "role": "member"})
        profile["clubs"] = None

    if settings.ADMIN_EMAIL and email.lower() == settings.ADMIN_EMAIL.lower() and profile.get("role") != "admin":
        admin_supabase.table("profiles").update({"role": "admin"}).eq("user_id", user_id).execute()
        profile["role"] = "admin"
    return profile


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> AuthenticatedUser:
    token = credentials.credentials
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供認證 Token",
        )

    try:
        user_client = get_user_supabase(token)
        user_resp = user_client.auth.get_user(token)
        if not user_resp or not user_resp.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="無效或已過期的登入憑證，請重新登入",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"認證驗證失敗: {str(e)}",
        )

    email = user_resp.user.email or ""
    try:
        profile = load_profile(get_admin_supabase(), user_resp.user.id, email)
    except Exception as e:
        err = str(e)
        if "profiles" in err and ("does not exist" in err or "schema cache" in err):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="尚未執行模組 9 的資料庫 SQL！請至 Supabase SQL Editor 執行 009_module9_clubs_and_scopes.sql",
            )
        raise HTTPException(status_code=500, detail=f"讀取社友資料失敗: {err}")

    club_rel = profile.get("clubs") or {}
    return AuthenticatedUser(
        id=user_resp.user.id,
        email=email,
        access_token=token,
        supabase=user_client,
        club_id=profile.get("club_id"),
        club_name=club_rel.get("name") if isinstance(club_rel, dict) else None,
        role=profile.get("role") or "member",
    )


async def require_club_member(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """必須已加入某個社（管理員例外）才能使用知識庫、聊天與文件功能。"""
    if not user.club_id and not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="請先輸入社內密碼加入所屬社，才能使用知識庫功能",
        )
    return user


async def require_admin(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """僅地區管理員可用。"""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="權限不足：此功能僅限地區管理員使用",
        )
    return user
