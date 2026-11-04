"""一次性工具：把所有尚未啟用的社，用統一預設密碼（settings.CLUB_DEFAULT_PASSWORD）直接啟用。
已啟用的社不動。可重複執行。用法：backend/venv/bin/python backend/scripts/activate_all_clubs.py"""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from app.auth import get_admin_supabase
from app.config import settings
from app.services import club_accounts as accounts, club_secrets

if not club_secrets.is_enabled():
    sys.exit("CLUB_PASSWORD_SECRET 未設定，請先設定再執行（否則後台看不到密碼）")

admin = get_admin_supabase()
clubs = admin.table("clubs").select("id, name, auth_user_id").order("name").execute().data or []
todo = [c for c in clubs if not c.get("auth_user_id")]
print(f"共 {len(clubs)} 社，已啟用 {len(clubs) - len(todo)}，待啟用 {len(todo)}")
ok, fail = 0, []
for c in todo:
    try:
        accounts.create_club_account(admin, c, settings.CLUB_DEFAULT_PASSWORD)
        ok += 1
    except Exception as e:
        fail.append((c["name"], str(e)[:100]))
print(f"啟用成功 {ok}，失敗 {len(fail)}")
for name, err in fail:
    print("  ✗", name, err)
