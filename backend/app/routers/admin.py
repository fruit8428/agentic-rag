"""模組 9：地區管理員 API — 社的新增／刪除／重設密碼、社友指派。"""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import AuthenticatedUser, get_admin_supabase, require_admin
from app.services.passwords import hash_password, validate_new_password

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminClubItem(BaseModel):
    id: str
    name: str
    division: Optional[str] = None
    code: Optional[str] = None
    has_password: bool
    member_count: int
    document_count: int
    created_at: Optional[str] = None


class CreateClubRequest(BaseModel):
    name: str
    password: str
    division: Optional[str] = None
    code: Optional[str] = None


class UpdateClubRequest(BaseModel):
    name: Optional[str] = None
    division: Optional[str] = None
    code: Optional[str] = None


class ResetClubPasswordRequest(BaseModel):
    new_password: str


class AdminMemberItem(BaseModel):
    user_id: str
    email: str
    role: str
    club_id: Optional[str] = None
    club_name: Optional[str] = None
    joined_at: Optional[str] = None
    created_at: Optional[str] = None


class UpdateMemberRequest(BaseModel):
    club_id: Optional[str] = None   # 傳 null 代表移出社
    role: Optional[str] = None      # 'member' | 'admin'


def _count_by(rows: list[dict], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        k = r.get(key)
        if k:
            counts[k] = counts.get(k, 0) + 1
    return counts


@router.get("/clubs", response_model=List[AdminClubItem])
async def admin_list_clubs(user: AuthenticatedUser = Depends(require_admin)):
    admin = get_admin_supabase()
    clubs = admin.table("clubs").select("id, name, division, code, password_hash, created_at").execute().data or []
    members = admin.table("profiles").select("club_id").not_.is_("club_id", "null").execute().data or []
    docs = admin.table("documents").select("club_id").eq("scope", "club").execute().data or []
    m_counts, d_counts = _count_by(members, "club_id"), _count_by(docs, "club_id")
    items = [
        AdminClubItem(
            id=c["id"], name=c["name"], division=c.get("division"), code=c.get("code"),
            has_password=bool(c.get("password_hash")),
            member_count=m_counts.get(c["id"], 0), document_count=d_counts.get(c["id"], 0),
            created_at=c.get("created_at"),
        )
        for c in clubs
    ]
    items.sort(key=lambda c: (c.division is None, c.code or "", c.name))
    return items


@router.post("/clubs", response_model=AdminClubItem)
async def admin_create_club(payload: CreateClubRequest, user: AuthenticatedUser = Depends(require_admin)):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="社名不能為空")
    try:
        validate_new_password(payload.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    admin = get_admin_supabase()
    if admin.table("clubs").select("id").eq("name", name).execute().data:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"社名「{name}」已存在")
    ins = admin.table("clubs").insert({
        "name": name,
        "division": (payload.division or "").strip() or None,
        "code": (payload.code or "").strip() or None,
        "password_hash": hash_password(payload.password),
    }).execute()
    c = ins.data[0]
    return AdminClubItem(id=c["id"], name=c["name"], division=c.get("division"), code=c.get("code"),
                         has_password=True, member_count=0, document_count=0, created_at=c.get("created_at"))


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
    items = await admin_list_clubs(user)
    return next(c for c in items if c.id == club_id)


@router.delete("/clubs/{club_id}")
async def admin_delete_club(club_id: str, user: AuthenticatedUser = Depends(require_admin)):
    """社內仍有社友或文件時拒絕刪除（防誤刪）。"""
    admin = get_admin_supabase()
    club = admin.table("clubs").select("id, name").eq("id", club_id).execute().data
    if not club:
        raise HTTPException(status_code=404, detail="找不到指定的社")
    member_count = len(admin.table("profiles").select("user_id").eq("club_id", club_id).execute().data or [])
    doc_count = len(admin.table("documents").select("id").eq("club_id", club_id).execute().data or [])
    if member_count or doc_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"無法刪除「{club[0]['name']}」：尚有 {member_count} 位社友與 {doc_count} 份文件。請先移出社友並刪除文件。",
        )
    admin.table("clubs").delete().eq("id", club_id).execute()
    return {"status": "deleted", "id": club_id, "name": club[0]["name"]}


@router.post("/clubs/{club_id}/reset-password")
async def admin_reset_club_password(
    club_id: str, payload: ResetClubPasswordRequest, user: AuthenticatedUser = Depends(require_admin)
):
    try:
        validate_new_password(payload.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    admin = get_admin_supabase()
    res = admin.table("clubs").update({"password_hash": hash_password(payload.new_password)}).eq("id", club_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="找不到指定的社")
    return {"status": "ok", "id": club_id, "name": res.data[0]["name"], "message": "社內密碼已重設"}


@router.get("/members", response_model=List[AdminMemberItem])
async def admin_list_members(user: AuthenticatedUser = Depends(require_admin)):
    admin = get_admin_supabase()
    profiles = admin.table("profiles").select("user_id, club_id, role, joined_at, created_at, clubs(name)").execute().data or []
    prof_by_id = {p["user_id"]: p for p in profiles}
    auth_users = admin.auth.admin.list_users()
    items: list[AdminMemberItem] = []
    for u in auth_users:
        p = prof_by_id.get(u.id, {})
        rel = p.get("clubs") or {}
        items.append(AdminMemberItem(
            user_id=u.id, email=u.email or "", role=p.get("role") or "member",
            club_id=p.get("club_id"), club_name=rel.get("name") if isinstance(rel, dict) else None,
            joined_at=p.get("joined_at"), created_at=str(u.created_at) if u.created_at else None,
        ))
    items.sort(key=lambda m: (m.club_name or "～", m.email))
    return items


@router.patch("/members/{user_id}", response_model=AdminMemberItem)
async def admin_update_member(user_id: str, payload: UpdateMemberRequest, user: AuthenticatedUser = Depends(require_admin)):
    """重新指派社友的社別（club_id 傳 null 代表移出），或變更角色。"""
    admin = get_admin_supabase()
    updates: dict = {}
    if "club_id" in payload.model_fields_set:
        if payload.club_id:
            if not admin.table("clubs").select("id").eq("id", payload.club_id).execute().data:
                raise HTTPException(status_code=404, detail="找不到指定的社")
        updates["club_id"] = payload.club_id
        updates["joined_at"] = None if payload.club_id is None else datetime.now(timezone.utc).isoformat()
    if payload.role is not None:
        if payload.role not in ("member", "admin"):
            raise HTTPException(status_code=400, detail="角色只能是 member 或 admin")
        if user_id == user.id and payload.role != "admin":
            raise HTTPException(status_code=400, detail="不能取消自己的管理員角色")
        updates["role"] = payload.role
    if not updates:
        raise HTTPException(status_code=400, detail="沒有要更新的欄位")
    res = admin.table("profiles").update(updates).eq("user_id", user_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="找不到指定的使用者")
    items = await admin_list_members(user)
    return next(m for m in items if m.user_id == user_id)
