"""模組 9 端到端權限測試（本機後端 127.0.0.1:8000 + 真實 Supabase）。全部使用臨時測試帳號/社，結束後清除。"""
import json, secrets, sys, time, requests
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from app.config import settings
from supabase import create_client

API = "http://127.0.0.1:8000"
admin_db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
tag = secrets.token_hex(3)
PW = "Test-" + secrets.token_urlsafe(12)
CLUB_PW_A, CLUB_PW_B = "club-a-" + secrets.token_hex(4), "club-b-" + secrets.token_hex(4)
users = {k: f"m9test-{k}-{tag}@example.com" for k in ("admin", "a", "b")}
results, created_user_ids, created_club_ids = [], [], []

def check(name, cond, info=""):
    results.append((name, bool(cond))); print(("✅" if cond else "❌"), name, info if not cond else "")

def api(method, path, token, **kw):
    r = requests.request(method, API + path, headers={"Authorization": f"Bearer {token}"}, timeout=120, **kw)
    try: body = r.json()
    except Exception: body = r.text
    return r.status_code, body

def signup_and_login(email):
    r = requests.post(API + "/api/auth/signup", json={"email": email, "password": PW}, timeout=60)
    assert r.ok, f"signup 失敗 {r.text}"
    c = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
    s = c.auth.sign_in_with_password({"email": email, "password": PW})
    created_user_ids.append(s.user.id)
    return s.user.id, s.session.access_token

def wait_completed(token, doc_id, timeout=120):
    for _ in range(timeout // 3):
        code, docs = api("GET", "/api/documents", token)
        d = next((x for x in docs if x["id"] == doc_id), None) if code == 200 else None
        if d and d["status"] in ("completed", "failed"): return d
        time.sleep(3)
    return None

def chat(token, thread_id, msg):
    r = requests.post(API + "/api/chat/stream", headers={"Authorization": f"Bearer {token}"},
                      json={"thread_id": thread_id, "message": msg}, stream=True, timeout=180)
    text, sources = "", []
    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"): continue
        try: ev = json.loads(line[5:].strip())
        except Exception: continue
        if ev.get("type") in ("token", "delta", "content"): text += ev.get("content") or ev.get("delta") or ""
        if ev.get("type") == "sources": sources = ev.get("sources") or []
        if "sources" in ev and isinstance(ev["sources"], list): sources = ev["sources"] or sources
        if ev.get("type") == "done" and ev.get("content"): text = ev["content"]
    return r.status_code, text, sources

try:
    # ---------- 帳號 ----------
    admin_id, admin_tok = signup_and_login(users["admin"])
    admin_db.table("profiles").update({"role": "admin"}).eq("user_id", admin_id).execute()
    a_id, a_tok = signup_and_login(users["a"]); b_id, b_tok = signup_and_login(users["b"])
    code, me = api("GET", "/api/clubs/me", admin_tok); check("管理員角色生效", code == 200 and me["role"] == "admin", me)

    # ---------- 未加入社：擋住 ----------
    code, _ = api("GET", "/api/threads", a_tok); check("未加入社 → /api/threads 403", code == 403, code)
    code, _ = api("GET", "/api/documents", a_tok); check("未加入社 → /api/documents 403", code == 403, code)
    code, _ = api("GET", "/api/admin/clubs", a_tok); check("一般使用者 → /api/admin 403", code == 403, code)

    # ---------- 管理員建兩個測試社 ----------
    code, ca = api("POST", "/api/admin/clubs", admin_tok, json={"name": f"測試甲社-{tag}", "password": CLUB_PW_A, "division": "99", "code": "99-1"})
    check("管理員新增甲社", code == 200, (code, ca)); created_club_ids.append(ca["id"])
    code, cb = api("POST", "/api/admin/clubs", admin_tok, json={"name": f"測試乙社-{tag}", "password": CLUB_PW_B, "division": "99", "code": "99-2"})
    check("管理員新增乙社", code == 200, (code, cb)); created_club_ids.append(cb["id"])
    code, _ = api("POST", "/api/admin/clubs", a_tok, json={"name": "x", "password": "123456"}); check("一般使用者不能建社", code == 403, code)
    code, lst = api("GET", "/api/clubs", a_tok); check("社名清單可見且含測試社", code == 200 and any(c["id"] == ca["id"] for c in lst), code)

    # ---------- 加入社 ----------
    code, _ = api("POST", "/api/clubs/join", a_tok, json={"club_id": ca["id"], "password": "wrong-pass"}); check("錯誤社內密碼 → 401", code == 401, code)
    code, m = api("POST", "/api/clubs/join", a_tok, json={"club_id": ca["id"], "password": CLUB_PW_A}); check("A 加入甲社", code == 200 and m["club_id"] == ca["id"], (code, m))
    code, _ = api("POST", "/api/clubs/join", a_tok, json={"club_id": cb["id"], "password": CLUB_PW_B}); check("已有社再加入 → 409", code == 409, code)
    code, m = api("POST", "/api/clubs/join", b_tok, json={"club_id": cb["id"], "password": CLUB_PW_B}); check("B 加入乙社", code == 200, (code, m))
    code, _ = api("GET", "/api/threads", a_tok); check("加入後 /api/threads 200", code == 200, code)

    # ---------- 上傳社內文件 ----------
    def upload(token, name, content, scope=None):
        data = {"scope": scope} if scope else {}
        r = requests.post(API + "/api/documents/upload", headers={"Authorization": f"Bearer {token}"},
                          files={"file": (name, content.encode(), "text/plain")}, data=data, timeout=120)
        return r.status_code, (r.json() if r.headers.get("content-type","").startswith("application/json") else r.text)
    code, da = upload(a_tok, f"甲社社內資料_{tag}.txt", "甲社社內機密：本社年度活動代號為 ALPHA-7788，聯絡人為王小明。" * 3)
    check("A 上傳社內文件", code == 200 and da.get("scope") == "club" and da.get("club_id") == ca["id"], (code, da))
    code, db_ = upload(b_tok, f"乙社社內資料_{tag}.txt", "乙社社內機密：本社年度活動代號為 BRAVO-9911，聯絡人為李大華。" * 3)
    check("B 上傳社內文件", code == 200 and db_.get("club_id") == cb["id"], (code, db_))
    code, _ = upload(a_tok, "x.txt", "test", scope="district"); check("一般社友上傳地區級 → 403", code == 403, code)
    code, dd = upload(admin_tok, f"地區公開測試_{tag}.txt", "地區公開資訊：2026 地區年會地點在台北國際會議中心，代號 DISTRICT-2026。" * 3, scope="district")
    check("管理員上傳地區級文件", code == 200 and dd.get("scope") == "district", (code, dd))
    fa, fb, fd = wait_completed(a_tok, da["id"]), wait_completed(b_tok, db_["id"]), wait_completed(admin_tok, dd["id"])
    check("三份文件處理完成", all(x and x["status"] == "completed" for x in (fa, fb, fd)), [x and x["status"] for x in (fa, fb, fd)])

    # ---------- 文件列表可見性 ----------
    code, docs_a = api("GET", "/api/documents", a_tok); ids_a = {d["id"] for d in docs_a}
    check("A 看得到自己社 + 地區文件", da["id"] in ids_a and dd["id"] in ids_a, ids_a)
    check("A 看不到乙社文件", db_["id"] not in ids_a)
    check("A 看到的文件全是 district 或甲社", all(d["scope"] == "district" or d["club_id"] == ca["id"] for d in docs_a))
    code, docs_admin = api("GET", "/api/documents", admin_tok); check("管理員看得到全部", {da["id"], db_["id"], dd["id"]} <= {d["id"] for d in docs_admin})

    # ---------- RLS 直接打 Supabase ----------
    cb_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY); cb_client.postgrest.auth(b_tok)
    rows = cb_client.table("documents").select("id").execute().data; ids = {r["id"] for r in rows}
    check("RLS：B 直連資料庫看不到甲社文件", da["id"] not in ids and db_["id"] in ids and dd["id"] in ids, ids)
    chunks = cb_client.table("document_chunks").select("document_id").execute().data
    check("RLS：B 直連看不到甲社分塊", all(c["document_id"] != da["id"] for c in chunks))
    check("RLS：B 讀不到 clubs 密碼雜湊", not cb_client.table("clubs").select("password_hash").execute().data)
    check("RLS：B 可讀 clubs_public", len(cb_client.table("clubs_public").select("id").execute().data) >= 81)

    # ---------- 檢索路徑 ----------
    code, _ = api("POST", "/api/documents/%s/extract-metadata" % db_["id"], a_tok); check("A 對乙社文件提取元數據 → 404", code == 404, code)
    code, _ = api("DELETE", "/api/documents/%s" % db_["id"], a_tok); check("A 刪乙社文件 → 404", code == 404, code)
    code, th = api("POST", "/api/threads", a_tok, json={"title": "權限測試"}); tid = th["id"]
    code, _ = api("POST", "/api/chat/stream", a_tok, json={"thread_id": tid, "message": "hi", "document_id": db_["id"]}); check("A 以乙社文件過濾聊天 → 404", code == 404, code)
    code, text, srcs = chat(a_tok, tid, "乙社的年度活動代號是什麼？請只根據知識庫回答")
    src_names = [s.get("filename", "") for s in srcs]
    check("A 問乙社機密：來源不含乙社文件", code == 200 and not any("乙社" in n for n in src_names), (code, src_names))
    check("A 問乙社機密：回答不含 BRAVO-9911", "BRAVO-9911" not in text, text[:120])
    code, text, srcs = chat(a_tok, tid, "甲社的年度活動代號是什麼？")
    check("A 問本社資料：找得到 ALPHA-7788", "ALPHA-7788" in text or any("甲社" in s.get("filename","") for s in srcs), (text[:120], [s.get("filename") for s in srcs]))
    code, text, srcs = chat(b_tok, (api("POST", "/api/threads", b_tok, json={"title": "t"})[1])["id"], "地區年會地點在哪裡？代號是什麼？")
    check("B 問地區資料：找得到 DISTRICT-2026", "DISTRICT-2026" in text or any("地區公開" in s.get("filename","") for s in srcs), (text[:120], [s.get("filename") for s in srcs]))
    code, text, srcs = chat(b_tok, (api("POST", "/api/threads", b_tok, json={"title": "t2"})[1])["id"], "幫我用 SQL 統計目前知識庫共有幾份文件")
    check("B Text-to-SQL 不含甲社文件", code == 200 and "甲社" not in text and not any("甲社" in s.get("filename","") for s in srcs), (text[:200], [s.get("filename") for s in srcs]))

    # ---------- 社密碼變更 ----------
    code, _ = api("POST", "/api/clubs/me/password", a_tok, json={"current_password": "bad", "new_password": "newpass123"}); check("錯舊密碼改密碼 → 401", code == 401, code)
    code, _ = api("POST", "/api/clubs/me/password", a_tok, json={"current_password": CLUB_PW_A, "new_password": "newpass123"}); check("A 更改甲社密碼", code == 200, code)

    # ---------- 管理員：刪社保護與指派 ----------
    code, body = api("DELETE", "/api/admin/clubs/%s" % ca["id"], admin_tok); check("刪有社友的社 → 409", code == 409, (code, body))
    code, _ = api("PATCH", "/api/admin/members/%s" % a_id, admin_tok, json={"club_id": None}); check("管理員移出 A", code == 200, code)
    code, _ = api("PATCH", "/api/admin/members/%s" % b_id, admin_tok, json={"club_id": None}); check("管理員移出 B", code == 200, code)
    code, _ = api("GET", "/api/threads", a_tok); check("被移出後 A 再次 403", code == 403, code)
    for d in (da, db_, dd):
        code, _ = api("DELETE", "/api/documents/%s" % d["id"], admin_tok); check(f"管理員刪除文件 {d['filename'][:8]}", code == 200, code)
    for cid in list(created_club_ids):
        code, _ = api("DELETE", "/api/admin/clubs/%s" % cid, admin_tok); check("刪除空測試社", code == 200, code)
        if code == 200: created_club_ids.remove(cid)
finally:
    # ---------- 清理 ----------
    for cid in created_club_ids:
        admin_db.table("profiles").update({"club_id": None}).eq("club_id", cid).execute()
        admin_db.table("documents").delete().eq("club_id", cid).execute()
        admin_db.table("clubs").delete().eq("id", cid).execute()
    admin_db.table("documents").delete().ilike("filename", f"%{tag}%").execute()
    for uid in created_user_ids:
        try: admin_db.auth.admin.delete_user(uid)
        except Exception as e: print("刪除測試帳號失敗", uid, e)
    print("\n清理完成。結果：", sum(1 for _, ok in results if ok), "/", len(results), "通過")
    failed = [n for n, ok in results if not ok]
    if failed: print("失敗項目：", failed)
