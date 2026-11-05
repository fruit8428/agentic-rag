"""聊天 API 防護測試：未登入被拒、每社每分鐘 N 次（後端請以 CHAT_RATE_LIMIT_PER_MINUTE=2 啟動以加速驗證）。
執行：E2E_API=http://127.0.0.1:8000 backend/venv/bin/python backend/tests/e2e_rate_limit.py"""
import os, secrets, sys, requests
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from app.config import settings
from supabase import create_client

API = os.environ.get("E2E_API", "http://127.0.0.1:8000")
LIMIT = settings.CHAT_RATE_LIMIT_PER_MINUTE
tag = secrets.token_hex(3)
admin_db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
results, uids, cids = [], [], []

def check(name, cond, info=""):
    results.append((name, bool(cond))); print(("✅" if cond else "❌"), name, "" if cond else info)

def api(method, path, token=None, **kw):
    r = requests.request(method, API + path, headers={"Authorization": f"Bearer {token}"} if token else {}, timeout=180, **kw)
    return r

try:
    r = api("POST", "/api/chat/stream", json={"thread_id": "00000000-0000-0000-0000-000000000000", "message": "hi"})
    check("未登入呼叫 chat → 401/403", r.status_code in (401, 403), r.status_code)
    r = api("POST", "/api/chat/stream", token="not-a-real-token", json={"thread_id": "00000000-0000-0000-0000-000000000000", "message": "hi"})
    check("假 token → 401", r.status_code == 401, r.status_code)

    email, pw = f"rladmin-{tag}@example.com", "Adm-" + tag
    u = admin_db.auth.admin.create_user({"email": email, "password": pw, "email_confirm": True}); uids.append(u.user.id)
    admin_db.table("profiles").upsert({"user_id": u.user.id, "role": "admin"}, on_conflict="user_id").execute()
    admin_tok = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY).auth.sign_in_with_password({"email": email, "password": pw}).session.access_token
    c = api("POST", "/api/admin/clubs", admin_tok, json={"name": f"限流測試社-{tag}", "division": "99", "code": "99-9"}).json(); cids.append(c["id"])
    tok = api("POST", "/api/auth/login", json={"club_id": c["id"], "password": settings.CLUB_DEFAULT_PASSWORD}).json()["access_token"]
    th = api("POST", "/api/threads", tok, json={"title": "限流"}).json()["id"]

    codes = []
    for i in range(LIMIT + 1):
        r = api("POST", "/api/chat/stream", tok, json={"thread_id": th, "message": "請只回答「好」"}, stream=True)
        codes.append(r.status_code)
        if r.status_code == 200:
            for _ in r.iter_lines(): pass  # 讀完串流
    print("連續呼叫狀態碼：", codes)
    check(f"前 {LIMIT} 次 200", all(x == 200 for x in codes[:LIMIT]), codes)
    check(f"第 {LIMIT + 1} 次 429", codes[-1] == 429, codes)
    check("429 回應有 Retry-After 與中文說明", r.status_code == 429 and r.headers.get("Retry-After") and "太頻繁" in r.json().get("detail", ""), (r.headers.get("Retry-After"), r.text[:120]))
finally:
    for cid in cids:
        try: api("DELETE", f"/api/admin/clubs/{cid}", admin_tok)
        except Exception: pass
    for uid in uids:
        try: admin_db.auth.admin.delete_user(uid)
        except Exception: pass
    failed = [n for n, ok in results if not ok]
    print(f"\n通過 {len(results) - len(failed)}/{len(results)}", ("失敗：" + str(failed)) if failed else "全部通過")
    sys.exit(1 if failed else 0)
