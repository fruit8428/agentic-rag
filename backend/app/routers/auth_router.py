from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from app.auth import get_admin_supabase

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupRequest(BaseModel):
    email: str
    password: str


class SignupResponse(BaseModel):
    message: str
    email: str


@router.post("/signup", response_model=SignupResponse)
async def signup_user(payload: SignupRequest):
    """
    使用 Supabase Admin API 建立已自動完成 Email 驗證的使用者帳號，
    讓開發測試時不需要去信箱收驗證信即可直接登入！
    """
    if len(payload.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密碼長度至少需要 6 個字元",
        )

    try:
        admin_client = get_admin_supabase()
        res = admin_client.auth.admin.create_user(
            {
                "email": payload.email,
                "password": payload.password,
                "email_confirm": True,
            }
        )
        if not res or not res.user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="建立帳號失敗，請確認信箱是否已被註冊",
            )
        return SignupResponse(
            message="註冊成功！已自動啟用帳號。",
            email=res.user.email or payload.email,
        )
    except HTTPException:
        raise
    except Exception as e:
        err_msg = str(e)
        if "already been registered" in err_msg or "already exists" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="此 Email 已經註冊過了，請直接切換至「登入」！",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"註冊失敗：{err_msg}",
        )
