"""模組 9／10：地區管理員 API — 社的新增／修改／刪除、啟用碼、重設社密碼。"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import AuthenticatedUser, get_admin_supabase, require_admin
from app.services import club_accounts as accounts

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminClubItem(BaseModel):
    id: str
    name: str
    division: Optional[str] = None
    code: Optional[str] = None
    activated: bool
    activation_code: Optional[str] = None   # 未啟用時才有值
    activated_at: Optional[str] = None
    document_count: int
    created_at: Optional[str] = None


class CreateClubRequest(BaseModel):
    name: str
    division: Optional[str] = None
    code: Optional[str] = None


class UpdateClubRequest(BaseModel):
    name: Optional[str] = None
    division: Optional[str] = None
    code: Optional[str] = None


class ResetClubPasswordRequest(BaseModel):
    new_password: str


_CLUB_COLUMNS = "id, name, division, code, auth_user_id, activation_code, activated_at, created_at"


def _to_item(c: dict, doc_counts: dict[str, int]) -> AdminClubItem:
    activated = bool(c.get("auth_user_id"))
    return AdminClubItem(
        id=c["id"], name=c["name"], division=c.get("division"), code=c.get("code"),
        activated=activated,
        activation_code=None if activated else c.get("activation_code"),
        activated_at=c.get("activated_at"),
        document_count=doc_counts.get(c["id"], 0),
        created_at=c.get("created_at"),
    )


def _doc_counts(admin) -> dict[str, int]:
    docs = admin.table("documents").select("club_id").eq("scope", "club").execute().data or []
    counts: dict[str, int] = {}
    for d in docs:
        if d.get("club_id"):
            counts[d["club_id"]] = counts.get(d["club_id"], 0) + 1
    return counts


def _get_club(admin, club_id: str) -> dict:
    rows = admin.table("clubs").select(_CLUB_COLUMNS).eq("id", club_id).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="找不到指定的社")
    return rows[0]


@router.get("/clubs", response_model=List[AdminClubItem])
async def admin_list_clubs(user: AuthenticatedUser = Depends(require_admin)):
    admin = get_admin_supabase()
    clubs = admin.table("clubs").select(_CLUB_COLUMNS).execute().data or []
    counts = _doc_counts(admin)
    items = [_to_item(c, counts) for c in clubs]
    items.sort(key=lambda c: (c.division is None, c.code or "", c.name))
    return items


@router.post("/clubs", response_model=AdminClubItem)
async def admin_create_club(payload: CreateClubRequest, user: AuthenticatedUser = Depends(require_admin)):
    """新增社並自動配發啟用碼（交給該社執秘做首次設定）。"""
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="社名不能為空")
    admin = get_admin_supabase()
    if admin.table("clubs").select("id").eq("name", name).execute().data:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"社名「{name}」已存在")
    ins = admin.table("clubs").insert({
        "name": name,
        "division": (payload.division or "").strip() or None,
        "code": (payload.code or "").strip() or None,
        "activation_code": accounts.generate_activation_code(),
    }).execute()
    return _to_item(ins.data[0], {})


@router.patch("/clubs/{club_id}", response_model=AdminClubItem)
async def admin_update_club(club_id: str, payload: UpdateClubRequest, user: AuthenticatedUser = Depends(require_admin)):
    admin = get_admin_supabase()
    updates: dict = {}
    if payload.name is not None:
        if not payload.name.strip():
            raise HTTPException(status_code=400, detail="社名不能為空")
        updates["name"] = payload.name.strip()
    if payload.division is not None:
        updates["division"] = payload.division.strip() or None
    if payload.code is not None:
        updates["code"] = payload.code.strip() or None
    if not updates:
        raise HTTPException(status_code=400, detail="沒有要更新的欄位")
    res = admin.table("clubs").update(updates).eq("id", club_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="找不到指定的社")
    return _to_item(_get_club(admin, club_id), _doc_counts(admin))


@router.delete("/clubs/{club_id}")
async def admin_delete_club(club_id: str, user: AuthenticatedUser = Depends(require_admin)):
    """社內仍有文件時拒絕刪除（防誤刪）；刪社時一併刪除該社的共用帳號。"""
    admin = get_admin_supabase()
    club = _get_club(admin, club_id)
    doc_count = len(admin.table("documents").select("id").eq("club_id", club_id).execute().data or [])
    if doc_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"無法刪除「{club['name']}」：尚有 {doc_count} 份社內文件，請先刪除文件。",
        )
    if club.get("auth_user_id"):
        # 先解除綁定再刪帳號（帳號刪除會連動刪掉 profiles 列，之後社才刪得掉）
        admin.table("clubs").update({"auth_user_id": None}).eq("id", club_id).execute()
        accounts.delete_account(admin, club["auth_user_id"])
    # 其他仍綁在此社的 profiles（例如管理員手動指派過的）一律解除
    admin.table("profiles").update({"club_id": None, "joined_at": None}).eq("club_id", club_id).execute()
    admin.table("clubs").delete().eq("id", club_id).execute()
    return {"status": "deleted", "id": club_id, "name": club["name"]}


@router.post("/clubs/{club_id}/activation-code", response_model=AdminClubItem)
async def admin_regenerate_activation_code(club_id: str, user: AuthenticatedUser = Depends(require_admin)):
    """重新產生啟用碼（僅限尚未啟用的社）。"""
    admin = get_admin_supabase()
    club = _get_club(admin, club_id)
    if club.get("auth_user_id"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="此社已啟用，請改用「重設密碼」")
    admin.table("clubs").update({"activation_code": accounts.generate_activation_code()}).eq("id", club_id).execute()
    return _to_item(_get_club(admin, club_id), _doc_counts(admin))


@router.post("/clubs/{club_id}/reset-password")
async def admin_reset_club_password(
    club_id: str, payload: ResetClubPasswordRequest, user: AuthenticatedUser = Depends(require_admin)
):
    """管理員直接為已啟用的社設定新密碼（社友忘記密碼時使用）。"""
    try:
        accounts.validate_new_password(payload.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    admin = get_admin_supabase()
    club = _get_club(admin, club_id)
    if not club.get("auth_user_id"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="此社尚未啟用，請把啟用碼交給該社做首次設定")
    accounts.set_account_password(admin, club["auth_user_id"], payload.new_password)
    return {"status": "ok", "id": club_id, "name": club["name"], "message": "社密碼已重設"}
