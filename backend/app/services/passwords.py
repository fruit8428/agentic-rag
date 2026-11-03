"""社內密碼的雜湊與驗證（bcrypt，絕不儲存明文）。"""
import bcrypt

MIN_PASSWORD_LENGTH = 6


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def validate_new_password(plain: str) -> None:
    if len(plain or "") < MIN_PASSWORD_LENGTH:
        raise ValueError(f"社內密碼至少需要 {MIN_PASSWORD_LENGTH} 個字元")
