"""模組 10 補充：社密碼紀錄的加密／解密。
Supabase Auth 只存雜湊、拿不回原文，所以另外用環境變數 CLUB_PASSWORD_SECRET 衍生的金鑰加密後存進 clubs.password_enc，
讓地區管理員在後台看得到各社目前的密碼。沒有設定金鑰時就不記錄（功能停用，不影響登入）。"""
import base64
import hashlib
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)


def _fernet() -> Optional[Fernet]:
    secret = (settings.CLUB_PASSWORD_SECRET or "").strip()
    if len(secret) < 16:
        return None
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def is_enabled() -> bool:
    return _fernet() is not None


def encrypt_password(plain: str) -> Optional[str]:
    f = _fernet()
    if not f:
        logger.warning("CLUB_PASSWORD_SECRET 未設定，略過社密碼紀錄")
        return None
    return f.encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_password(token: Optional[str]) -> Optional[str]:
    f = _fernet()
    if not f or not token:
        return None
    try:
        return f.decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        # 金鑰被更換過，舊紀錄解不開
        return None
