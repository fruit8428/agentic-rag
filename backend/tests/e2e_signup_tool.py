"""報名系統橋接工具端到端測試。
後端須先以 SIGNUP_SUPABASE_URL=http://127.0.0.1:8765 啟動（本腳本會在該埠開一個假的 Supabase REST，回傳假報名資料，
所以不會碰到正式報名資料庫）。臨時社與管理員測完自動刪除。
執行：E2E_API=http://127.0.0.1:8000 backend/venv/bin/python backend/tests/e2e_signup_tool.py
"""
import json, os, secrets, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import requests
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from app.config import settings
from supabase import create_client

API = os.environ.get("E2E_API", "http://127.0.0.1:8000")
MOCK_PORT = 8765
tag = secrets.token_hex(3)
CLUB_A, CLUB_B, CLUB_C = f"測試甲社-{tag}", f"測試乙社-{tag}", f"測試丙社-{tag}"
admin_db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
results, created_user_ids, created_club_ids = [], [], []

FAKE_MAIN = {
    "divisionsData": [{"id": 99, "name": "第九十九分區", "clubs": [{"name": CLUB_A}, {"name": CLUB_B}, {"name": CLUB_C}]}],
    "categoriesData": [{"id": "sports", "name": "⚽ 運動賽事", "subEvents": ["2. 地區保齡球聯誼賽"]}],
    "chairConfig": {"bankAccount": "上海商銀 999-000-123456（測試）"},
    "registrationOrders": {"2. 地區保齡球聯誼賽": [
        {"clubName": CLUB_A, "submittedAt": "2026-11-01 10:00", "grandTotal": 3000,
         "items": [{"role": "社長", "nickname": "Tony", "name": "王假名", "type": "參賽", "diet": "葷"},
                   {"name": "李假名", "type": "只用餐", "diet": "素"}], "prizeSponsors": []},
        {"clubName": CLUB_B, "submittedAt": "2026-11-02 09:00", "grandTotal": 1500,
         "items": [{"name": "張乙社獨有假名", "type": "參賽", "diet": "葷"}], "prizeSponsors": []},
    ]},
    "lastUpdated": "2026-11-05T01:00:00Z",
}
FAKE_PAY = {"sports::2. 地區保齡球聯誼賽": {CLUB_A: {"status": "NOTIFIED", "amount": 3000, "remitNote": "甲社保齡球", "remitAmount": 3000, "remitDate": "2026-11-03"}}}

class MockSupabase(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        body = json.dumps([{"key": settings.SIGNUP_STORAGE_KEY, "value": FAKE_MAIN}, {"key": settings.SIGNUP_PAYMENT_KEY, "value": FAKE_PAY}], ensure_ascii=False).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

server = HTTPServer(("127.0.0.1", MOCK_PORT), MockSupabase)
threading.Thread(target=server.serve_forever, daemon=True).start()

def check(name, cond, info=""):
    results.append((name, bool(cond))); print(("✅" if cond else "❌"), name, "" if cond else info)

def api(method, path, token=None, **kw):
    r = requests.request(method, API + path, headers={"Authorization": f"Bearer {token}"} if token else {}, timeout=120, **kw)
    try: body = r.json()
    except Exception: body = r.text
    return r.status_code, body

def chat(token, thread_id, msg):
    r = requests.post(API + "/api/chat/stream", headers={"Authorization": f"Bearer {token}"}, json={"thread_id": thread_id, "message": msg}, stream=True, timeout=180)
    text, tools, sources = "", [], []
    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"): continue
        try: ev = json.loads(line[5:].strip())
        except Exception: continue
        if ev.get("type") == "delta": text += ev.get("content") or ""
        if ev.get("type") == "tool_start": tools.append(ev.get("tool"))
        if isinstance(ev.get("sources"), list): sources = ev["sources"] or sources
        if ev.get("type") == "error": text += f"[ERROR {ev.get('error')}]"
    return text, tools, sources

def ask(token, title, msg):
    _, th = api("POST", "/api/threads", token, json={"title": title})
    text, tools, sources = chat(token, th["id"], msg)
    print(f"\n🗨️  {msg}\n🔧 工具：{tools}\n🤖 {text[:600]}\n")
    return text, tools, sources

try:
    u = admin_db.auth.admin.create_user({"email": f"sgadmin-{tag}@example.com", "password": "Adm-" + tag, "email_confirm": True})
    created_user_ids.append(u.user.id)
    admin_db.table("profiles").upsert({"user_id": u.user.id, "role": "admin"}, on_conflict="user_id").execute()
    admin_tok = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY).auth.sign_in_with_password({"email": f"sgadmin-{tag}@example.com", "password": "Adm-" + tag}).session.access_token

    code, ca = api("POST", "/api/admin/clubs", admin_tok, json={"name": CLUB_A, "division": "99", "code": "99-1"}); created_club_ids.append(ca["id"])
    code, cb = api("POST", "/api/admin/clubs", admin_tok, json={"name": CLUB_B, "division": "99", "code": "99-2"}); created_club_ids.append(cb["id"])
    code, cc = api("POST", "/api/admin/clubs", admin_tok, json={"name": CLUB_C, "division": "99", "code": "99-3"}); created_club_ids.append(cc["id"])
    _, sc = api("POST", "/api/auth/login", json={"club_id": cc["id"], "password": settings.CLUB_DEFAULT_PASSWORD}); c_tok = sc["access_token"]
    _, sa = api("POST", "/api/auth/login", json={"club_id": ca["id"], "password": settings.CLUB_DEFAULT_PASSWORD}); a_tok = sa["access_token"]
    _, sb = api("POST", "/api/auth/login", json={"club_id": cb["id"], "password": settings.CLUB_DEFAULT_PASSWORD}); b_tok = sb["access_token"]
    check("兩個臨時社登入成功", a_tok and b_tok)

    text, tools, sources = ask(a_tok, "報名查詢", "我們社報名了什麼活動？報了哪些人？")
    check("甲社：呼叫報名工具", "get_my_club_registration" in tools, tools)
    check("甲社：答出保齡球與名單", "保齡球" in text and "王假名" in text and "李假名" in text, text[:200])
    check("甲社：來源卡片為報名系統", any(s.get("match_type") == "signup" for s in sources), sources[:1])

    text, tools, _ = ask(a_tok, "繳費查詢", "我們社保齡球的費用繳了嗎？")
    check("甲社：繳費回答提到已回報匯款、尚未核對", "get_my_club_registration" in tools and ("尚未核對" in text or "回報" in text or "核對" in text), text[:200])

    text, tools, _ = ask(a_tok, "問他社", f"{CLUB_B} 有沒有報名保齡球？他們報了誰？")
    check("甲社問乙社：不呼叫工具或被拒絕", ("get_my_club_registration" not in tools) or ("只能" in text or "自己" in text or "無法" in text), (tools, text[:200]))
    check("甲社問乙社：沒有洩漏乙社名單", "張乙社獨有假名" not in text, text[:300])

    text, tools, _ = ask(b_tok, "乙社自查", "我們社報了誰？")
    check("乙社：只看到自己的名單", "張乙社獨有假名" in text and "王假名" not in text, text[:300])

    text, tools, _ = ask(c_tok, "無報名", "我們社報名了什麼？")
    check("丙社：呼叫工具且明確說沒有報名", "get_my_club_registration" in tools and ("沒有" in text or "尚未" in text or "無" in text), text[:200])
    check("丙社：沒有看到別社的名單", "王假名" not in text and "張乙社獨有假名" not in text, text[:200])

    text, tools, _ = ask(admin_tok, "管理員指定社", f"請幫我查 {CLUB_A} 的報名狀態")
    check("管理員：可指定社名查詢", "get_my_club_registration" in tools and "王假名" in text, text[:200])
finally:
    server.shutdown()
    for cid in created_club_ids:
        try: api("DELETE", f"/api/admin/clubs/{cid}", admin_tok)
        except Exception: pass
    for uid in created_user_ids:
        try: admin_db.auth.admin.delete_user(uid)
        except Exception: pass
    failed = [n for n, ok in results if not ok]
    print(f"\n通過 {len(results) - len(failed)}/{len(results)}", ("失敗：" + str(failed)) if failed else "全部通過")
    sys.exit(1 if failed else 0)
