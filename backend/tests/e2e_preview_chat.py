"""對 Vercel Preview（有登入保護）實測 AI 問答：經 `vercel curl` 發請求。
臨時管理員／臨時社用 service role 建立，測完刪除。不會寫入報名系統。
用法：E2E_API=https://<preview> backend/venv/bin/python backend/tests/e2e_preview_chat.py"""
import json, os, secrets, subprocess, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from app.config import settings
from supabase import create_client

API = os.environ["E2E_API"].rstrip("/")
tag = secrets.token_hex(3)
admin_db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
results, uids, cids = [], [], []

def check(name, cond, info=""):
    results.append((name, bool(cond))); print(("✅" if cond else "❌"), name, "" if cond else str(info)[:300])

def vcurl(method, path, token=None, body=None):
    cmd = ["vercel", "curl", API + path, "-s", "-X", method, "-w", "\n__HTTP__%{http_code}"]
    if token: cmd += ["-H", f"Authorization: Bearer {token}"]
    if body is not None: cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(body, ensure_ascii=False)]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=240).stdout
    # vercel 會在前面印幾行自己的訊息，只取最後的回應
    i = out.rfind("__HTTP__"); code = int(out[i+8:].strip() or 0); text = out[:i]
    # 去掉 vercel CLI 的前言（回應從第一個 { 或 [ 或 data: 開始）
    for marker in ("data:", "{", "["):
        j = text.find(marker)
        if j != -1: text = text[j:]; break
    return code, text

def api(method, path, token=None, **kw):
    code, text = vcurl(method, path, token, kw.get("json"))
    try: return code, json.loads(text)
    except Exception: return code, text

def chat(token, thread_id, msg):
    code, text = vcurl("POST", "/api/chat/stream", token, {"thread_id": thread_id, "message": msg})
    reply, tools, sources = "", [], []
    for line in text.splitlines():
        if not line.startswith("data:"): continue
        try: ev = json.loads(line[5:].strip())
        except Exception: continue
        if ev.get("type") == "delta": reply += ev.get("content") or ""
        if ev.get("type") == "tool_start": tools.append(ev.get("tool"))
        if isinstance(ev.get("sources"), list) and ev["sources"]: sources = ev["sources"]
        if ev.get("type") == "error": reply += f"[ERROR {ev.get('error')}]"
    return code, reply, tools, sources

def ask(token, title, msg):
    _, th = api("POST", "/api/threads", token, json={"title": title})
    code, reply, tools, sources = chat(token, th["id"], msg)
    print(f"\n🗨️  {msg}\n🔧 {tools}  來源類型 {[s.get('match_type') for s in sources]}\n🤖 {reply[:500]}\n")
    return reply, tools, sources

try:
    email, pw = f"pvadmin-{tag}@example.com", "Adm-" + secrets.token_urlsafe(10)
    u = admin_db.auth.admin.create_user({"email": email, "password": pw, "email_confirm": True}); uids.append(u.user.id)
    admin_db.table("profiles").upsert({"user_id": u.user.id, "role": "admin"}, on_conflict="user_id").execute()
    admin_tok = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY).auth.sign_in_with_password({"email": email, "password": pw}).session.access_token
    code, me = api("GET", "/api/clubs/me", admin_tok); check("Preview：臨時管理員可登入", code == 200 and me.get("role") == "admin", (code, me))

    code, c = api("POST", "/api/admin/clubs", admin_tok, json={"name": f"預覽測試社-{tag}", "division": "99", "code": "99-7"}); cids.append(c["id"])
    code, s = api("POST", "/api/auth/login", json={"club_id": c["id"], "password": settings.CLUB_DEFAULT_PASSWORD}); club_tok = s["access_token"]
    check("Preview：臨時社可登入", bool(club_tok))

    r, t, src = ask(admin_tok, "C-8", "請幫我查 台北松山扶輪社 的報名狀態，報了誰？")
    check("C-8 管理員指定社：列出 GMS 與兩位社友", "get_my_club_registration" in t and "李瑞琦" in r and "楊富中" in r and "獎助金" in r, r[:200])
    check("C-1 來源卡片為報名系統即時資料", any(x.get("match_type") == "signup" for x in src), src[:1])

    r, t, _ = ask(admin_tok, "C-2", "台北松山扶輪社 獎助金管理研討會的費用繳了嗎？")
    check("C-2 繳費狀態：回答未繳", "get_my_club_registration" in t and ("未繳" in r or "尚未" in r), r[:200])

    r, t, _ = ask(club_tok, "C-7", "我們社報名了什麼活動？")
    check("C-7 沒報名的社：明確說沒有", "get_my_club_registration" in t and ("沒有" in r or "無" in r), r[:200])

    r, t, _ = ask(club_tok, "C-4", "台北松山扶輪社有沒有報名？他們報了誰？")
    check("C-4 問他社：被拒且不洩漏名單", "李瑞琦" not in r and "楊富中" not in r, r[:300])

    r, t, src = ask(admin_tok, "C-5", "請問民生社有誰得獎？")
    check("C-5 知識庫有答案：走知識庫檢索", "search_knowledge_base" in t and any(x.get("match_type") in ("hybrid", "keyword", "vector") for x in src), (t, r[:200]))

    r, t, _ = ask(club_tok, "C-6", "請問 2031 年地區年會的主辦飯店訂在哪裡？")
    check("C-6 沒答案的問題：不編造（說沒有資料或改用網路搜尋）", any(k in r for k in ("沒有", "無法", "查無", "尚未", "找不到", "未提供", "網路")), r[:300])
finally:
    for cid in cids:
        try: api("DELETE", f"/api/admin/clubs/{cid}", admin_tok)
        except Exception: pass
    for uid in uids:
        try: admin_db.auth.admin.delete_user(uid)
        except Exception: pass
    failed = [n for n, ok in results if not ok]
    print(f"\n通過 {len(results) - len(failed)}/{len(results)}", ("失敗：" + str(failed)) if failed else "全部通過")
