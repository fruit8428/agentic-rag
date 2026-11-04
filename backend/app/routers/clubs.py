"""模組 9／10：社（club）相關 API — 我的社、變更本社密碼。"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import AuthenticatedUser, get_admin_supabase, get_current_user, require_club_member
from app.services import club_accounts as accounts

router = APIRouter(prefix="/api/clubs", tags=["clubs"])


class MyClubResponse(BaseModel):
    user_id: str
    email: str
    role: str
    club_id: Optional[str] = None
    club_name: Optional[str] = None


class ChangeClubPasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.get("/me", response_model=MyClubResponse)
async def my_club(user: AuthenticatedUser = Depends(get_current_user)):
    return MyClubResponse(
        user_id=user.id,
        email=user.email,
        role=user.role,
        club_id=user.club_id,
        club_name=user.club_name,
    )


@router.post("/me/password")
async def change_my_club_password(
    payload: ChangeClubPasswordRequest,
    user: AuthenticatedUser = Depends(require_club_member),
):
    """以目前的密碼更換新密碼（社帳號改社密碼；管理員改管理員密碼）。"""
    try:
        accounts.validate_new_password(payload.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    key = f"change:{user.id}"
    accounts.check_throttle(key)
    if not accounts.sign_in(user.email, payload.current_password):
        accounts.record_failure(key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="目前的密碼錯誤")
    accounts.clear_failures(key)

    admin = get_admin_supabase()
    if user.club_id and not user.is_admin:
        accounts.set_club_password(admin, user.club_id, user.id, payload.new_password)
    else:
        accounts.set_account_password(admin, user.id, payload.new_password)
    label = "管理員密碼" if user.is_admin and not user.club_id else "社密碼"
    return {"status": "ok", "club_id": user.club_id, "club_name": user.club_name, "message": f"{label}已更新"}
