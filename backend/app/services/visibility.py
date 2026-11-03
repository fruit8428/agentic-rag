"""
模組 9：文件可見性規則（地區／社內分級）

規則（與資料庫 RLS 的 can_view_document() 完全一致）：
    使用者 U 能看到文件 D ⇔ D.scope = 'district'
                          或 D.club_id = U.club_id
                          或 U 是地區管理員

後端的檢索路徑（混合檢索、Text-to-SQL、子代理）為了效能使用 Service Role 連線，
會繞過 RLS，因此「每一個」用管理員連線查 documents / document_chunks 的地方，
都必須透過這個模組建立查詢，確保規則不會漏套。
"""
from typing import Optional

from fastapi import HTTPException, status
from supabase import Client

from app.auth import AuthenticatedUser


def apply_visibility(query, user: AuthenticatedUser):
    """在 documents 查詢建構器上套用可見性條件。管理員不過濾。"""
    if user.is_admin:
        return query
    if user.club_id:
        return query.or_(f"scope.eq.district,club_id.eq.{user.club_id}")
    return query.eq("scope", "district")


def visible_documents_query(
    admin_supabase: Client,
    user: AuthenticatedUser,
    select: str = "*",
    status_filter: Optional[str] = None,
):
    """回傳已套用可見性規則的 documents 查詢建構器（呼叫端可再加 order / eq 等條件後 execute）。"""
    q = admin_supabase.table("documents").select(select)
    if status_filter:
        q = q.eq("status", status_filter)
    return apply_visibility(q, user)


def visible_document_ids(
    admin_supabase: Client,
    user: AuthenticatedUser,
    status_filter: Optional[str] = "completed",
) -> set[str]:
    res = visible_documents_query(admin_supabase, user, select="id", status_filter=status_filter).execute()
    return {d["id"] for d in (res.data or [])}


def can_view(user: AuthenticatedUser, doc: dict) -> bool:
    if user.is_admin:
        return True
    if doc.get("scope") == "district":
        return True
    return bool(user.club_id) and doc.get("club_id") == user.club_id


def fetch_visible_document(
    admin_supabase: Client,
    user: AuthenticatedUser,
    document_id: str,
    select: str = "*",
) -> dict:
    """讀取單一文件；不存在或無權查看一律回 404（不洩漏文件是否存在）。"""
    res = admin_supabase.table("documents").select(select).eq("id", document_id).execute()
    if not res.data or not can_view(user, res.data[0]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到指定的文件，或您沒有權限查看")
    return res.data[0]


def flatten_club_name(doc: dict) -> dict:
    """把 PostgREST 內嵌的 clubs(name) 攤平成 club_name 欄位。"""
    item = dict(doc)
    rel = item.pop("clubs", None)
    item["club_name"] = rel.get("name") if isinstance(rel, dict) else None
    return item


def scope_label(doc: dict) -> str:
    if doc.get("scope") == "district":
        return "地區公開"
    return f"{doc.get('club_name') or '社內'} 社內"
