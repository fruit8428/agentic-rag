"""模組 9：社（club）相關 API — 社名清單、我的社、以社內密碼加入、變更本社密碼。"""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import AuthenticatedUser, get_admin_supabase, get_current_user, require_club_member
from app.services.passwords import hash_password, validate_new_password, verify_password

router = APIRouter(prefix="/api/clubs", tags=["clubs"])


class ClubPublicItem(BaseModel):
    id: str
    name: str
    division: Optional[str] = None
    code: Optional[str] = None
    joinable: bool


class MyClubResponse(BaseModel):
    user_id: str
    email: str
    role: str
    club_id: Optional[str] = None
    club_name: Optional[str] = None


class JoinClubRequest(BaseModel):
    club_id: str
    password: str


class ChangeClubPasswordRequest(BaseModel):
    current_password: str
    new_password: str


def _club_sort_key(c: dict):
    return (c.get("division") is None, c.get("code") or "", c.get("name") or "")


@router.get("", response_model=List[ClubPublicItem])
async def list_clubs(user: AuthenticatedUser = Depends(get_current_user)):
    """所有登入者都能看到社名清單（加入社時選用），不回傳密碼雜湊。"""
    admin = get_admin_supabase()
    res = admin.table("clubs").select("id, name, division, code, password_hash").execute()
    items = [
        {
            "id": c["id"],
            "name": c["name"],
            "division": c.get("division"),
            "code": c.get("code"),
            "joinable": bool(c.get("password_hash")),
        }
        for c in (res.data or [])
    ]
    items.sort(key=_club_sort_key)
    return items


@router.get("/me", response_model=MyClubResponse)
async def my_club(user: AuthenticatedUser = Depends(get_current_user)):
    return MyClubResponse(
        user_id=user.id,
        email=user.email,
        role=user.role,
        club_id=user.club_id,
        club_name=user.club_name,
    )


@router.post("/join", response_model=MyClubResponse)
async def join_club(payload: JoinClubRequest, user: AuthenticatedUser = Depends(get_current_user)):
    """輸入社內密碼加入所屬社。一人只能屬於一個社；已加入者需由管理員重新指派。"""
    if user.club_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"您已是「{user.club_name}」的社友；若需更換社別請聯絡地區管理員",
        )
    admin = get_admin_supabase()
    club_res = admin.table("clubs").select("id, name, password_hash").eq("id", payload.club_id).execute()
    if not club_res.data:
        raise HTTPException(status_code=404, detail="找不到指定的社")
    club = club_res.data[0]
    if not club.get("password_hash"):
        raise HTTPException(status_code=400, detail="此社尚未設定社內密碼，請聯絡地區管理員設定後再加入")
    if not verify_password(payload.password, club["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="社內密碼錯誤，請向貴社執秘確認")

    admin.table("profiles").update(
        {"club_id": club["id"], "joined_at": datetime.now(timezone.utc).isoformat()}
    ).eq("user_id", user.id).execute()

    return MyClubResponse(user_id=user.id, email=user.email, role=user.role, club_id=club["id"], club_name=club["name"])


@router.post("/me/password")
async def change_my_club_password(
    payload: ChangeClubPasswordRequest,
    user: AuthenticatedUser = Depends(require_club_member),
):
    """社友以目前的社內密碼更換新密碼（自己的社自己設定）。"""
    if not user.club_id:
        raise HTTPException(status_code=400, detail="您尚未加入任何社")
    try:
        validate_new_password(payload.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    admin = get_admin_supabase()
    club_res = admin.table("clubs").select("id, name, password_hash").eq("id", user.club_id).execute()
    if not club_res.data:
        raise HTTPException(status_code=404, detail="找不到您所屬的社")
    club = club_res.data[0]
    if not verify_password(payload.current_password, club.get("password_hash")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="目前的社內密碼錯誤")

    admin.table("clubs").update({"password_hash": hash_password(payload.new_password)}).eq("id", club["id"]).execute()
    return {"status": "ok", "club_id": club["id"], "club_name": club["name"], "message": "社內密碼已更新"}
