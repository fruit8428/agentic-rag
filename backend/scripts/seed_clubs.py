"""匯入某地區的扶輪社名單到 clubs 表（新地區上線用）。
CSV 格式：division,code,name（見 supabase/seed/clubs.3523.csv），另外會自動補一筆「地區辦公室」。
已存在的社名會跳過（可重複執行）。加 --activate 會順便用統一預設密碼（CLUB_DEFAULT_PASSWORD）啟用新匯入的社。

用法：
  backend/venv/bin/python backend/scripts/seed_clubs.py --district 3481            # 只匯入名單
  backend/venv/bin/python backend/scripts/seed_clubs.py --district 3481 --activate # 匯入並啟用
  backend/venv/bin/python backend/scripts/seed_clubs.py --district 3481 --dry-run  # 只印出要做什麼，不寫資料庫
會先印出目標 Supabase 網址，要輸入 yes 才開始（--dry-run 不用）。
"""
import argparse, csv, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.auth import get_admin_supabase
from app.config import settings
from app.services import club_accounts as accounts

ROOT = Path(__file__).resolve().parent.parent.parent

ap = argparse.ArgumentParser()
ap.add_argument("--district", required=True, help="地區代號，例如 3481（會讀 supabase/seed/clubs.<代號>.csv）")
ap.add_argument("--file", help="自訂 CSV 路徑（預設 supabase/seed/clubs.<代號>.csv）")
ap.add_argument("--activate", action="store_true", help="匯入後用預設密碼啟用新社")
ap.add_argument("--dry-run", action="store_true", help="只檢查與列出，不寫入")
args = ap.parse_args()

csv_path = Path(args.file) if args.file else ROOT / "supabase" / "seed" / f"clubs.{args.district}.csv"
if not csv_path.exists():
    sys.exit(f"找不到名單檔：{csv_path}")
with open(csv_path, encoding="utf-8-sig", newline="") as f:
    rows = [r for r in csv.DictReader(f) if (r.get("name") or "").strip()]
if not rows:
    sys.exit("CSV 沒有任何社")
for r in rows:
    r["name"] = r["name"].strip()
    r["division"] = (r.get("division") or "").strip() or None
    r["code"] = (r.get("code") or "").strip() or None
if not any(r["name"] == "地區辦公室" for r in rows):
    rows.append({"division": None, "code": None, "name": "地區辦公室"})
names = [r["name"] for r in rows]
dups = {n for n in names if names.count(n) > 1}
if dups:
    sys.exit(f"CSV 有重複社名：{sorted(dups)}")

print(f"地區代號（後端設定）：{settings.DISTRICT_CODE}；名單檔：{csv_path.name}，共 {len(rows)} 社（含地區辦公室）")
print(f"目標 Supabase：{settings.SUPABASE_URL}")
if settings.DISTRICT_CODE != args.district:
    print(f"⚠️  後端 DISTRICT_CODE={settings.DISTRICT_CODE} 與 --district {args.district} 不同，請確認 .env 指向正確的地區資料庫")
if args.dry_run:
    print("（dry-run）將匯入：", "、".join(names[:8]), "…" if len(names) > 8 else "")
    sys.exit(0)
if input("確定要寫入這個資料庫嗎？輸入 yes 繼續：").strip().lower() != "yes":
    sys.exit("已取消")

admin = get_admin_supabase()
existing = {c["name"] for c in (admin.table("clubs").select("name").execute().data or [])}
todo = [r for r in rows if r["name"] not in existing]
print(f"資料庫已有 {len(existing)} 社，將新增 {len(todo)} 社，跳過 {len(rows) - len(todo)} 社")
if todo:
    admin.table("clubs").insert([{"division": r["division"], "code": r["code"], "name": r["name"]} for r in todo]).execute()
if args.activate:
    clubs = admin.table("clubs").select("id, name, auth_user_id").execute().data or []
    pending = [c for c in clubs if not c.get("auth_user_id")]
    ok, fail = 0, []
    for c in pending:
        try:
            accounts.create_club_account(admin, c, settings.CLUB_DEFAULT_PASSWORD); ok += 1
        except Exception as e:
            fail.append((c["name"], str(e)[:100]))
    print(f"啟用成功 {ok}，失敗 {len(fail)}")
    for n, err in fail: print("  ✗", n, err)
print("完成")
