"""模組 10 端到端測試：社共用登入（啟用碼註冊、社名登入、改密碼、管理員重設）＋ 模組 9 可見性規則。
目標網址由 E2E_API 指定（預設本機 127.0.0.1:8000）。全部使用臨時測試社／帳號，結束後清除。"""
import json, os, secrets, sys, time, requests
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from app.config import settings
from supabase import create_client

API = os.environ.get("E2E_API", "http://127.0.0.1:8000")
admin_db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
tag = secrets.token_hex(3)
ADMIN_EMAIL_T = f"m10admin-{tag}@example.com"
ADMIN_PW_T = "Adm-" + secrets.token_urlsafe(12)
PW_A, PW_B = "club-a-" + secrets.token_hex(4), "club-b-" + secrets.token_hex(4)
results, created_user_ids, created_club_ids = [], [], []

def check(name, cond, info=""):
    results.append((name, bool(cond))); print(("✅" if cond else "❌"), name, info if not cond else "")

def api(method, path, token=None, **kw):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = requests.request(method, API + path, headers=headers, timeout=120, **kw)
    try: body = r.json()
    except Exception: body = r.text
    return r.status_code, body

def login(club_id=None, password="", as_admin=False):
    return api("POST", "/api/auth/login", json={"club_id": club_id, "as_admin": as_admin, "password": password})

def wait_completed(token, doc_id, timeout=150):
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
        if "sources" in ev and isinstance(ev["sources"], list): sources = ev["sources"] or sources
        if ev.get("type") == "done" and ev.get("content"): text = ev["content"]
    return r.status_code, text, sources

def upload(token, name, content, scope=None):
    data = {"scope": scope} if scope else {}
    r = requests.post(API + "/api/documents/upload", headers={"Authorization": f"Bearer {token}"},
                      files={"file": (name, content.encode(), "text/plain")}, data=data, timeout=120)
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text)

try:
    # ---------- 臨時管理員（直接用 Supabase Admin API 建立，不走公開 API） ----------
    u = admin_db.auth.admin.create_user({"email": ADMIN_EMAIL_T, "password": ADMIN_PW_T, "email_confirm": True})
    created_user_ids.append(u.user.id)
    admin_db.table("profiles").upsert({"user_id": u.user.id, "role": "admin"}, on_conflict="user_id").execute()
    anon = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
    admin_tok = anon.auth.sign_in_with_password({"email": ADMIN_EMAIL_T, "password": ADMIN_PW_T}).session.access_token
    code, me = api("GET", "/api/clubs/me", admin_tok); check("臨時管理員角色生效", code == 200 and me["role"] == "admin", me)

    # ---------- 公開端點 ----------
    code, pub = api("GET", "/api/auth/clubs"); check("公開社名清單 200 且 ≥ 81 社", code == 200 and len(pub) >= 81, (code, len(pub) if code == 200 else pub))
    check("公開清單不含啟用碼／密碼欄位", code == 200 and all("activation_code" not in c and "password_hash" not in c for c in pub))
    code, cfg = api("GET", "/api/auth/config"); check("公開設定 200", code == 200 and "admin_contact" in cfg, (code, cfg))
    code, _ = login(as_admin=True, password="definitely-wrong-" + tag); check("管理員錯密碼 → 401", code == 401, code)
    code, _ = api("GET", "/api/clubs/me"); check("沒有 token → 401/403", code in (401, 403), code)

    # ---------- 管理員建測試社（自動配發啟用碼） ----------
    code, ca = api("POST", "/api/admin/clubs", admin_tok, json={"name": f"測試甲社-{tag}", "division": "99", "code": "99-1", "auto_activate": False})
    check("新增甲社並取得啟用碼", code == 200 and not ca["activated"] and ca["activation_code"], (code, ca)); created_club_ids.append(ca["id"])
    code, cb = api("POST", "/api/admin/clubs", admin_tok, json={"name": f"測試乙社-{tag}", "division": "99", "code": "99-2", "auto_activate": False})
    check("新增乙社", code == 200, (code, cb)); created_club_ids.append(cb["id"])
    code, cc = api("POST", "/api/admin/clubs", admin_tok, json={"name": f"測試丙社-{tag}", "division": "99", "code": "99-3", "auto_activate": False})
    check("新增丙社", code == 200, (code, cc)); created_club_ids.append(cc["id"])
    code, _ = api("POST", "/api/admin/clubs", admin_tok, json={"name": f"測試甲社-{tag}"}); check("重複社名 → 409", code == 409, code)

    # ---------- 預設密碼直接啟用（新社預設行為） ----------
    code, cd = api("POST", "/api/admin/clubs", admin_tok, json={"name": f"測試丁社-{tag}", "division": "99", "code": "99-4"})
    check("新增丁社：預設直接啟用且後台看得到預設密碼", code == 200 and cd["activated"] and cd["password"] == settings.CLUB_DEFAULT_PASSWORD, (code, cd)); created_club_ids.append(cd["id"])
    code, sd = login(cd["id"], settings.CLUB_DEFAULT_PASSWORD); check("丁社用預設密碼登入", code == 200, (code, sd))
    d_tok = sd["access_token"]
    code, me_d = api("GET", "/api/clubs/me", d_tok); check("丁社 /me 標示仍用預設密碼", code == 200 and me_d["using_default_password"] is True, me_d)
    NEW_D = "own-d-" + secrets.token_hex(4)
    code, _ = api("POST", "/api/clubs/me/password", d_tok, json={"current_password": settings.CLUB_DEFAULT_PASSWORD, "new_password": NEW_D}); check("丁社自行改掉預設密碼", code == 200, code)
    code, _ = api("GET", "/api/clubs/me", d_tok); check("改密碼後舊 session 失效（前端需自動重新登入）", code == 401, code)
    code, sd = login(cd["id"], NEW_D); d_tok = sd["access_token"]
    code, me_d = api("GET", "/api/clubs/me", d_tok); check("重新登入後 /me 不再標示預設密碼", code == 200 and me_d["using_default_password"] is False, me_d)
    code, _ = login(cd["id"], settings.CLUB_DEFAULT_PASSWORD); check("改完後預設密碼失效 → 401", code == 401, code)

    # ---------- 首次進入(註冊) ----------
    code, _ = login(ca["id"], PW_A); check("未啟用的社登入 → 409", code == 409, code)
    code, _ = api("POST", "/api/auth/register", json={"club_id": ca["id"], "activation_code": "ZZZZ-ZZZZ", "password": PW_A}); check("錯啟用碼 → 401", code == 401, code)
    code, _ = api("POST", "/api/auth/register", json={"club_id": ca["id"], "activation_code": ca["activation_code"], "password": "123"}); check("密碼太短 → 400", code == 400, code)
    code, _ = api("POST", "/api/auth/register", json={"club_id": "00000000-0000-0000-0000-000000000000", "activation_code": "AAAA-BBBB", "password": PW_A}); check("不存在的社 → 404", code == 404, code)
    lower_code = ca["activation_code"].lower().replace("-", " ")
    code, sa = api("POST", "/api/auth/register", json={"club_id": ca["id"], "activation_code": lower_code, "password": PW_A})
    check("甲社用啟用碼完成首次設定（小寫／無連字號也可）", code == 200 and sa.get("access_token") and sa["club_id"] == ca["id"], (code, sa))
    a_tok = sa["access_token"]
    code, me = api("GET", "/api/clubs/me", a_tok); check("甲社帳號 /me 綁定甲社", code == 200 and me["club_id"] == ca["id"] and me["role"] == "member", me)
    code, _ = api("POST", "/api/auth/register", json={"club_id": ca["id"], "activation_code": ca["activation_code"], "password": PW_A}); check("已啟用的社再註冊 → 409", code == 409, code)
    code, pub = api("GET", "/api/auth/clubs"); check("公開清單顯示甲社已啟用", any(c["id"] == ca["id"] and c["activated"] for c in pub))

    # ---------- 社名登入 ----------
    code, _ = login(ca["id"], "wrong-" + tag); check("甲社錯密碼 → 401", code == 401, code)
    code, s2 = login(ca["id"], PW_A); check("甲社正確密碼登入", code == 200 and s2.get("club_name") == ca["name"], (code, s2))
    code, _ = api("GET", "/api/admin/clubs", a_tok); check("社帳號 → /api/admin 403", code == 403, code)
    code, _ = api("POST", "/api/admin/clubs", a_tok, json={"name": "x"}); check("社帳號不能建社", code == 403, code)

    # ---------- 管理員：啟用碼管理 ----------
    code, lst = api("GET", "/api/admin/clubs", admin_tok)
    row_a = next(c for c in lst if c["id"] == ca["id"]); row_b = next(c for c in lst if c["id"] == cb["id"])
    check("管理員清單：甲社已啟用且不再顯示啟用碼", row_a["activated"] and row_a["activation_code"] is None, row_a)
    check("管理員清單：甲社密碼紀錄 = 註冊時設定的密碼", row_a.get("password") == PW_A, row_a.get("password"))
    check("管理員清單：未啟用的乙社沒有密碼", row_b.get("password") is None)
    check("管理員清單：乙社未啟用且有啟用碼", not row_b["activated"] and row_b["activation_code"], row_b)
    code, nb = api("POST", f"/api/admin/clubs/{cb['id']}/activation-code", admin_tok); check("重新產生乙社啟用碼", code == 200 and nb["activation_code"] != row_b["activation_code"], (code, nb))
    code, _ = api("POST", f"/api/admin/clubs/{ca['id']}/activation-code", admin_tok); check("已啟用社重產啟用碼 → 409", code == 409, code)
    code, _ = api("POST", "/api/auth/register", json={"club_id": cb["id"], "activation_code": row_b["activation_code"], "password": PW_B}); check("舊啟用碼失效 → 401", code == 401, code)
    code, sb = api("POST", "/api/auth/register", json={"club_id": cb["id"], "activation_code": nb["activation_code"], "password": PW_B}); check("乙社用新啟用碼完成設定", code == 200, (code, sb))
    b_tok = sb["access_token"]
    code, _ = api("POST", f"/api/admin/clubs/{cc['id']}/reset-password", admin_tok, json={"new_password": "abcdef12"}); check("未啟用社重設密碼 → 409", code == 409, code)

    # ---------- 文件可見性（模組 9 規則沿用） ----------
    code, da = upload(a_tok, f"甲社社內資料_{tag}.txt", "甲社社內機密：本社年度活動代號為 ALPHA-7788，聯絡人為王小明。" * 3)
    check("甲社上傳社內文件", code == 200 and da.get("scope") == "club" and da.get("club_id") == ca["id"], (code, da))
    code, db_ = upload(b_tok, f"乙社社內資料_{tag}.txt", "乙社社內機密：本社年度活動代號為 BRAVO-9911，聯絡人為李大華。" * 3)
    check("乙社上傳社內文件", code == 200 and db_.get("club_id") == cb["id"], (code, db_))
    code, _ = upload(a_tok, "x.txt", "test", scope="district"); check("社帳號上傳地區級 → 403", code == 403, code)
    code, dd = upload(admin_tok, f"地區公開測試_{tag}.txt", "地區公開資訊：2026 地區年會地點在台北國際會議中心，代號 DISTRICT-2026。" * 3, scope="district")
    check("管理員上傳地區級文件", code == 200 and dd.get("scope") == "district", (code, dd))
    fa, fb, fd = wait_completed(a_tok, da["id"]), wait_completed(b_tok, db_["id"]), wait_completed(admin_tok, dd["id"])
    check("三份文件處理完成", all(x and x["status"] == "completed" for x in (fa, fb, fd)), [x and x["status"] for x in (fa, fb, fd)])
    code, docs_a = api("GET", "/api/documents", a_tok); ids_a = {d["id"] for d in docs_a}
    check("甲社看得到本社 + 地區文件", da["id"] in ids_a and dd["id"] in ids_a, ids_a)
    check("甲社看不到乙社文件", db_["id"] not in ids_a)
    code, docs_admin = api("GET", "/api/documents", admin_tok); check("管理員看得到全部", {da["id"], db_["id"], dd["id"]} <= {d["id"] for d in docs_admin})
    cb_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY); cb_client.postgrest.auth(b_tok)
    ids = {r["id"] for r in cb_client.table("documents").select("id").execute().data}
    check("RLS：乙社直連資料庫看不到甲社文件", da["id"] not in ids and db_["id"] in ids and dd["id"] in ids, ids)
    check("RLS：乙社讀不到 clubs 表的啟用碼", not cb_client.table("clubs").select("activation_code").execute().data)
    code, _ = api("DELETE", "/api/documents/%s" % db_["id"], a_tok); check("甲社刪乙社文件 → 404", code == 404, code)
    code, th = api("POST", "/api/threads", a_tok, json={"title": "權限測試"}); tid = th["id"]
    code, text, srcs = chat(a_tok, tid, "乙社的年度活動代號是什麼？請只根據知識庫回答")
    check("甲社問乙社機密：來源不含乙社文件", code == 200 and not any("乙社" in s.get("filename", "") for s in srcs), (code, [s.get("filename") for s in srcs]))
    check("甲社問乙社機密：回答不含 BRAVO-9911", "BRAVO-9911" not in text, text[:120])
    code, text, srcs = chat(a_tok, tid, "甲社的年度活動代號是什麼？")
    check("甲社問本社資料：找得到 ALPHA-7788", "ALPHA-7788" in text or any("甲社" in s.get("filename", "") for s in srcs), (text[:120], [s.get("filename") for s in srcs]))
    code, text, srcs = chat(b_tok, (api("POST", "/api/threads", b_tok, json={"title": "t"})[1])["id"], "地區年會地點在哪裡？代號是什麼？")
    check("乙社問地區資料：找得到 DISTRICT-2026", "DISTRICT-2026" in text or any("地區公開" in s.get("filename", "") for s in srcs), (text[:120], [s.get("filename") for s in srcs]))

    # ---------- 改密碼 ----------
    NEW_A = "new-a-" + secrets.token_hex(4)
    code, _ = api("POST", "/api/clubs/me/password", a_tok, json={"current_password": "bad", "new_password": NEW_A}); check("錯舊密碼改密碼 → 401", code == 401, code)
    code, _ = api("POST", "/api/clubs/me/password", a_tok, json={"current_password": PW_A, "new_password": NEW_A}); check("甲社自行更改社密碼", code == 200, code)
    code, _ = login(ca["id"], PW_A); check("改密碼後舊密碼失效 → 401", code == 401, code)
    code, _ = login(ca["id"], NEW_A); check("改密碼後新密碼可登入", code == 200, code)
    code, lst = api("GET", "/api/admin/clubs", admin_tok); check("社自行改密碼後後台紀錄同步更新", next(c for c in lst if c["id"] == ca["id"])["password"] == NEW_A)
    NEW_B = "reset-b-" + secrets.token_hex(4)
    code, _ = api("POST", f"/api/admin/clubs/{cb['id']}/reset-password", admin_tok, json={"new_password": NEW_B}); check("管理員重設乙社密碼", code == 200, code)
    code, _ = login(cb["id"], NEW_B); check("乙社用管理員重設的密碼登入", code == 200, code)
    code, lst = api("GET", "/api/admin/clubs", admin_tok); check("管理員重設後後台紀錄同步更新", next(c for c in lst if c["id"] == cb["id"])["password"] == NEW_B)
    code, pub = api("GET", "/api/auth/clubs"); check("公開清單不含密碼紀錄", all("password" not in c and "password_enc" not in c for c in pub))

    # ---------- 登入節流（記憶體版，正式環境多個執行個體時不保證） ----------
    codes = [login(cc["id"] if False else cb["id"], "wrong-" + str(i))[0] for i in range(9)]
    if API.startswith("http://127.0.0.1"): check("連續 9 次錯密碼 → 第 9 次 429", codes[-1] == 429, codes)
    else: print("ℹ️  節流（正式環境）：", codes[-1], "（無伺服器環境不保證一定 429）")

    # ---------- 刪社保護與清除 ----------
    code, body = api("DELETE", "/api/admin/clubs/%s" % ca["id"], admin_tok); check("刪有文件的社 → 409", code == 409, (code, body))
    for d in (da, db_, dd):
        code, _ = api("DELETE", "/api/documents/%s" % d["id"], admin_tok); check(f"管理員刪除文件 {d['filename'][:8]}", code == 200, code)
    code, _ = api("DELETE", "/api/admin/clubs/%s" % ca["id"], admin_tok); check("刪除已啟用的甲社（連同帳號）", code == 200, code)
    if code == 200: created_club_ids.remove(ca["id"])
    code, _ = login(ca["id"], NEW_A); check("甲社刪除後登入 → 404", code == 404, code)
    code, _ = api("GET", "/api/clubs/me", a_tok); check("甲社舊 token 失效", code in (401, 403, 404), code)
    for cid in list(created_club_ids):
        code, _ = api("DELETE", "/api/admin/clubs/%s" % cid, admin_tok); check("刪除測試社", code == 200, code)
        if code == 200: created_club_ids.remove(cid)
finally:
    for cid in created_club_ids:
        row = admin_db.table("clubs").select("auth_user_id").eq("id", cid).execute().data
        admin_db.table("profiles").update({"club_id": None}).eq("club_id", cid).execute()
        admin_db.table("documents").delete().eq("club_id", cid).execute()
        admin_db.table("clubs").delete().eq("id", cid).execute()
        if row and row[0].get("auth_user_id"):
            try: admin_db.auth.admin.delete_user(row[0]["auth_user_id"])
            except Exception as e: print("刪除社帳號失敗", e)
    admin_db.table("documents").delete().ilike("filename", f"%{tag}%").execute()
    for uid in created_user_ids:
        try: admin_db.auth.admin.delete_user(uid)
        except Exception as e: print("刪除測試帳號失敗", uid, e)
    print("\n清理完成。結果：", sum(1 for _, ok in results if ok), "/", len(results), "通過")
    failed = [n for n, ok in results if not ok]
    if failed: print("失敗項目：", failed)
