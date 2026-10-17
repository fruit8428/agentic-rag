from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from app.auth import AuthenticatedUser, get_current_user

router = APIRouter(prefix="/api/threads", tags=["threads"])


class ThreadCreate(BaseModel):
    title: Optional[str] = "新對話"


class ThreadItem(BaseModel):
    id: str
    user_id: str
    title: str
    created_at: str
    updated_at: str


class MessageItem(BaseModel):
    id: str
    thread_id: str
    user_id: str
    role: str
    content: str
    sources: Optional[list] = []
    created_at: str


@router.get("", response_model=List[ThreadItem])
async def list_threads(user: AuthenticatedUser = Depends(get_current_user)):
    """取得當前用戶的所有對話線程（依更新時間倒序排列）。"""
    try:
        res = (
            user.supabase.table("threads")
            .select("*")
            .order("updated_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        err_str = str(e)
        if "relation" in err_str and "does not exist" in err_str:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="尚未在 Supabase 建立資料表！請先至 Supabase SQL Editor 執行 supabase/migrations/001_module1_schema.sql",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"讀取對話列表失敗: {err_str}",
        )


@router.post("", response_model=ThreadItem)
async def create_thread(
    payload: ThreadCreate, user: AuthenticatedUser = Depends(get_current_user)
):
    """建立新的對話線程。"""
    try:
        res = (
            user.supabase.table("threads")
            .insert({"user_id": user.id, "title": payload.title or "新對話"})
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=400, detail="無法建立對話線程")
        return res.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"建立對話線程失敗: {str(e)}",
        )


@router.delete("/{thread_id}")
async def delete_thread(
    thread_id: str, user: AuthenticatedUser = Depends(get_current_user)
):
    """刪除指定的對話線程（會自動連帶刪除其中的 messages）。"""
    try:
        user.supabase.table("threads").delete().eq("id", thread_id).execute()
        return {"status": "deleted", "id": thread_id}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"刪除對話線程失敗: {str(e)}",
        )


@router.get("/{thread_id}/messages", response_model=List[MessageItem])
async def list_messages(
    thread_id: str, user: AuthenticatedUser = Depends(get_current_user)
):
    """取得指定對話線程內的所有歷史訊息。"""
    try:
        res = (
            user.supabase.table("messages")
            .select("*")
            .eq("thread_id", thread_id)
            .order("created_at", desc=False)
            .execute()
        )
        return res.data or []
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"讀取訊息失敗: {str(e)}",
        )
