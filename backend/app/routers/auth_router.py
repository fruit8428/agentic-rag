"""模組 10：登入／首次註冊 API（不需登入即可呼叫）。
前端只會傳社 id、啟用碼與密碼，合成 Email 與管理員 Email 都留在後端。"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.auth import get_admin_supabase
from app.config import settings
from app.services import club_accounts as accounts

router = APIRouter(prefix="/api/auth", tags=["auth"])

ADMIN_KEY = "admin"


class ClubPublicItem(BaseModel):
    id: str
    name: str
    division: Optional[str] = None
    code: Optional[str] = None
    activated: bool


class AuthConfig(BaseModel):
    admin_contact: Optional[str] = None
    district_code: str = ""
    district_name: str = ""


class LoginRequest(BaseModel):
    club_id: Optional[str] = None   # 一般社登入
    as_admin: bool = False          # 地區管理員登入
    password: str


class RegisterRequest(BaseModel):
    club_id: str
    activation_code: str
    password: str


class SessionResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: Optional[int] = None
    token_type: str = "bearer"
    club_id: Optional[str] = None
    club_name: Optional[str] = None
    role: str = "member"


def _sort_key(c: dict):
    return (c.get("division") is None, c.get("code") or "", c.get("name") or "")


@router.get("/clubs", response_model=List[ClubPublicItem])
async def public_clubs():
    """登入頁的社名下拉清單（不需登入）。只回傳社名與是否已啟用，不含任何密碼或啟用碼。"""
    admin = get_admin_supabase()
    rows = admin.table("clubs").select("id, name, division, code, auth_user_id").execute().data or []
    items = [
        {"id": c["id"], "name": c["name"], "division": c.get("division"), "code": c.get("code"),
         "activated": bool(c.get("auth_user_id"))}
        for c in rows
    ]
    items.sort(key=_sort_key)
    return items


@router.get("/config", response_model=AuthConfig)
async def auth_config():
    """登入頁用的公開設定：管理員聯絡方式、地區代號與名稱（前端標題、信件主旨用）。"""
    return AuthConfig(
        admin_contact=settings.ADMIN_CONTACT or None,
        district_code=settings.DISTRICT_CODE,
        district_name=settings.DISTRICT_NAME,
    )


@router.post("/login", response_model=SessionResponse)
async def login(payload: LoginRequest):
    admin = get_admin_supabase()
    if payload.as_admin:
        key = ADMIN_KEY
        email = settings.ADMIN_EMAIL
        club = None
    else:
        if not payload.club_id:
            raise HTTPException(status_code=400, detail="請先選擇所屬社名")
        rows = admin.table("clubs").select("id, name, auth_user_id").eq("id", payload.club_id).execute().data
        if not rows:
            raise HTTPException(status_code=404, detail="找不到指定的社")
        club = rows[0]
        if not club.get("auth_user_id"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="此社尚未完成首次設定，請切換到「首次進入(註冊)」，輸入管理員提供的啟用碼",
            )
        key = club["id"]
        email = accounts.club_login_email(club["id"])

    accounts.check_throttle(key)
    session = accounts.sign_in(email, payload.password)
    if not session:
        accounts.record_failure(key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="密碼錯誤，請再試一次；忘記密碼請聯絡地區管理員重設",
        )
    accounts.clear_failures(key)
    return SessionResponse(
        access_token=session["access_token"],
        refresh_token=session["refresh_token"],
        expires_in=session.get("expires_in"),
        token_type=session.get("token_type") or "bearer",
        club_id=club["id"] if club else None,
        club_name=club["name"] if club else None,
        role="admin" if payload.as_admin else "member",
    )


@router.post("/register", response_model=SessionResponse)
async def register(payload: RegisterRequest):
    """首次進入：用管理員發的啟用碼為社建立帳號並設定社密碼，成功後直接登入。"""
    try:
        accounts.validate_new_password(payload.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    admin = get_admin_supabase()
    rows = admin.table("clubs").select("id, name, auth_user_id, activation_code").eq("id", payload.club_id).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="找不到指定的社")
    club = rows[0]
    if club.get("auth_user_id"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="此社已完成首次設定，請改用「社名登入」；忘記密碼請聯絡地區管理員",
        )
    if not club.get("activation_code"):
        raise HTTPException(status_code=400, detail="此社尚未配發啟用碼，請聯絡地區管理員")

    key = f"register:{club['id']}"
    accounts.check_throttle(key)
    if accounts.normalize_code(payload.activation_code) != club["activation_code"]:
        accounts.record_failure(key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="啟用碼錯誤，請向地區管理員確認")
    accounts.clear_failures(key)

    try:
        accounts.create_club_account(admin, club, payload.password)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"建立社帳號失敗：{e}")

    session = accounts.sign_in(accounts.club_login_email(club["id"]), payload.password)
    if not session:
        raise HTTPException(status_code=500, detail="帳號已建立但自動登入失敗，請改用「社名登入」")
    return SessionResponse(
        access_token=session["access_token"],
        refresh_token=session["refresh_token"],
        expires_in=session.get("expires_in"),
        token_type=session.get("token_type") or "bearer",
        club_id=club["id"],
        club_name=club["name"],
        role="member",
    )
