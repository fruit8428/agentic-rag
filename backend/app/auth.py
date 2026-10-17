from dataclasses import dataclass
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


def get_admin_supabase() -> Client:
    """回傳具備 Service Role 權限的 Supabase Client（僅用於系統管理操作，如免驗證信註冊）。"""
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def get_user_supabase(access_token: str) -> Client:
    """
    回傳綁定當前使用者 JWT 的 Supabase Client。
    所有透過此 Client 進行的資料庫查詢都會觸發 Postgres 行級安全性 (RLS)，
    確保 auth.uid() = user_id，使用者絕對看不到別人的資料。
    """
    client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
    client.postgrest.auth(access_token)
    return client


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
        return AuthenticatedUser(
            id=user_resp.user.id,
            email=user_resp.user.email or "",
            access_token=token,
            supabase=user_client,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"認證驗證失敗: {str(e)}",
        )
