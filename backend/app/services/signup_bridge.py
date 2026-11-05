"""
報名系統橋接（Signup Bridge）

讓 AI 小幫手能回答「我們社報名了什麼、繳費了沒」這類問題。
資料來源是本地區「活動整合報名系統」的 Supabase（與本專案不同的 Supabase 專案，由 SIGNUP_SUPABASE_URL 指定），
該系統把整個狀態存成一包 JSON 放在 `app_storage` 表，本模組只用 anon key **唯讀**取回並整理。

安全邊界：
- 只有 GET，沒有任何寫入。
- 一般使用者只能查「登入社」自己的資料，傳入的社名一律忽略；地區管理員才可指定社名。
- 回傳給模型的是整理過的摘要，不是整包 JSON，所以模型看不到其他社的資料。
"""
from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from app.auth import AuthenticatedUser
from app.config import settings

# 60 秒記憶體快取：同一個執行個體內短時間多次提問不用重抓整包 JSON
_CACHE_TTL_SECONDS = 60
_cache: dict[str, Any] = {"fetched_at": 0.0, "state": None}

PAID_STATUSES = {"PAID_EMAIL", "PAID_MANUAL", "EXEMPT"}

STATUS_LABEL = {
    "PAID_EMAIL": "✅ 已繳（銀行入帳已核對）",
    "PAID_MANUAL": "✅ 已繳（主委手動核訖）",
    "EXEMPT": "✅ 免繳",
    "NOTIFIED": "🕒 已回報匯款，主委尚未核對",
    "UNPAID": "❌ 未繳",
}


def is_configured() -> bool:
    return bool(settings.SIGNUP_SUPABASE_URL and settings.SIGNUP_SUPABASE_ANON_KEY)


async def fetch_signup_state(force: bool = False) -> Optional[dict]:
    """取回報名系統的主資料與繳費紀錄，合併成一個 dict；未設定或失敗回 None。"""
    if not is_configured():
        return None
    now = time.time()
    if not force and _cache["state"] is not None and now - _cache["fetched_at"] < _CACHE_TTL_SECONDS:
        return _cache["state"]

    keys = [settings.SIGNUP_STORAGE_KEY, settings.SIGNUP_PAYMENT_KEY]
    key_list = ",".join(f'"{k}"' for k in keys)
    url = f"{settings.SIGNUP_SUPABASE_URL.rstrip('/')}/rest/v1/app_storage"
    headers = {
        "apikey": settings.SIGNUP_SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {settings.SIGNUP_SUPABASE_ANON_KEY}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.get(url, params={"select": "key,value", "key": f"in.({key_list})"}, headers=headers)
        res.raise_for_status()
        rows = res.json() or []

    by_key = {r.get("key"): r.get("value") for r in rows}
    main = by_key.get(settings.SIGNUP_STORAGE_KEY) or {}
    payment = by_key.get(settings.SIGNUP_PAYMENT_KEY)
    if not isinstance(payment, dict) or not payment:
        payment = main.get("chairPaymentRecords") or {}

    state = {
        "registrationOrders": main.get("registrationOrders") or {},
        "categoriesData": main.get("categoriesData") or [],
        "divisionsData": main.get("divisionsData") or [],
        "chairConfig": main.get("chairConfig") or {},
        "chairPaymentRecords": payment,
        "lastUpdated": main.get("lastUpdated"),
    }
    _cache["state"] = state
    _cache["fetched_at"] = now
    return state


# ---------- 純函式：從整包狀態整理出「某一社」的摘要（方便單元測試） ----------

def _find_division(divisions: list, club_name: str) -> Optional[str]:
    for d in divisions or []:
        for c in d.get("clubs") or []:
            if (c.get("name") if isinstance(c, dict) else c) == club_name:
                return d.get("name") or (f"第 {d.get('id')} 分區" if d.get("id") else None)
    return None


def _category_for_sub_event(categories: list, sub_event: str) -> Optional[dict]:
    for cat in categories or []:
        if sub_event in (cat.get("subEvents") or []):
            return cat
    return None


def _payment_key(cat: Optional[dict], sub_event: str) -> Optional[str]:
    return f"{cat['id']}::{sub_event}" if cat and cat.get("id") else None


def _fee_for(chair_config: dict, cat: Optional[dict], sub_event: str) -> Optional[int]:
    """研討會／年會類的每社應繳（分攤）金額：先看子活動設定，再退回頂層 fallback。"""
    key = _payment_key(cat, sub_event)
    fees = (chair_config.get("subEventFees") or {}).get(key or "", {}) if key else {}
    val = fees.get("feeApportionment")
    if val in (None, "", 0):
        val = chair_config.get("feeApportionment")
    try:
        return int(val) if val not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _format_bank_account(acct) -> Optional[str]:
    """chairConfig.bankAccount 可能是字串或 {bankName, bankCode, branch, accountName, accountNo}，統一成一行文字。"""
    if not acct:
        return None
    if isinstance(acct, str):
        return acct.strip() or None
    if not isinstance(acct, dict):
        return None
    no = (acct.get("accountNo") or "").strip()
    if not no:
        return None
    parts = [(acct.get("bankName") or "").strip()]
    if acct.get("bankCode"):
        parts[0] += f"（代碼 {acct['bankCode']}）"
    if acct.get("branch"):
        parts.append(str(acct["branch"]).strip())
    line = " ".join(p for p in parts if p)
    line += f"，帳號 {no}"
    if acct.get("accountName"):
        line += f"，戶名 {acct['accountName']}"
    return line


def _item_line(item: dict) -> str:
    parts = []
    role = (item.get("role") or "").strip()
    nick = (item.get("nickname") or "").strip()
    name = (item.get("name") or "").strip()
    who = " ".join(p for p in [role, nick, name] if p) or "（未填姓名）"
    parts.append(who)
    if item.get("type"):
        parts.append(str(item["type"]))
    diet = item.get("diet")
    if diet:
        parts.append(f"{diet}{'（' + item['veganNote'] + '）' if item.get('veganNote') else ''}")
    if item.get("handicap") not in (None, ""):
        parts.append(f"差點 {item['handicap']}")
    return "、".join(parts)


def summarize_club_registration(state: dict, club_name: str) -> dict:
    """整理某社在所有子活動的報名與繳費狀態。回傳結構化 dict，另有 format_* 轉成 Markdown。"""
    orders_by_event: dict = state.get("registrationOrders") or {}
    categories: list = state.get("categoriesData") or []
    payments: dict = state.get("chairPaymentRecords") or {}
    chair_config: dict = state.get("chairConfig") or {}

    events: dict[str, dict] = {}

    # 1. 該社送出過的報名表
    for sub_event, orders in orders_by_event.items():
        for order in orders or []:
            if (order or {}).get("clubName") != club_name:
                continue
            cat = _category_for_sub_event(categories, sub_event)
            items = order.get("items") or []
            entry = events.setdefault(sub_event, {
                "sub_event": sub_event,
                "category": (cat or {}).get("name"),
                "payment_key": _payment_key(cat, sub_event),
            })
            entry.update({
                "submitted_at": order.get("submittedAt"),
                "grand_total": order.get("grandTotal"),
                "participant_count": len(items),
                "participants": [_item_line(i) for i in items],
                "prize_sponsor_count": len(order.get("prizeSponsors") or []),
                "sponsor_tier": order.get("sponsorTier") or None,
                "sponsor_amount": order.get("sponsorAmount") or 0,
            })

    # 2. 該社的繳費紀錄（分攤金類活動可能沒有報名表、只有繳費紀錄）
    for pkey, records in payments.items():
        # 只認「大類id::子活動名稱」格式；舊版的 seminars / conference 兩桶報名系統已不再讀取，這裡也跳過
        if "::" not in pkey:
            continue
        rec = (records or {}).get(club_name) if isinstance(records, dict) else None
        if not rec:
            continue
        cat_id, sub_event = pkey.split("::", 1)
        cat = next((c for c in categories if c.get("id") == cat_id), None)
        entry = events.setdefault(sub_event, {
            "sub_event": sub_event,
            "category": (cat or {}).get("name"),
            "payment_key": pkey,
        })
        status = rec.get("status") or "UNPAID"
        entry["payment"] = {
            "status": status,
            "status_label": STATUS_LABEL.get(status, status),
            "is_paid": status in PAID_STATUSES,
            "amount": rec.get("amount"),
            "method": rec.get("method"),
            "date": rec.get("date"),
            "note": rec.get("note"),
            "remit_note": rec.get("remitNote"),
            "remit_amount": rec.get("remitAmount"),
            "remit_date": rec.get("remitDate"),
        }
        if entry.get("grand_total") is None:
            entry["required_fee"] = _fee_for(chair_config, cat, sub_event)

    # 3. 有報名表但沒有繳費紀錄 → 視為未繳（與報名系統 isPaid 判斷一致）
    for entry in events.values():
        if "payment" not in entry:
            entry["payment"] = {"status": "UNPAID", "status_label": STATUS_LABEL["UNPAID"], "is_paid": False}

    return {
        "club_name": club_name,
        "division": _find_division(state.get("divisionsData") or [], club_name),
        "bank_account": _format_bank_account(chair_config.get("bankAccount")),
        "events": sorted(events.values(), key=lambda e: e["sub_event"]),
        "data_updated_at": state.get("lastUpdated"),
    }


def format_club_registration_markdown(summary: dict) -> str:
    club = summary["club_name"]
    division = f"（{summary['division']}）" if summary.get("division") else ""
    lines = [f"### {club}{division} 的報名與繳費狀態"]
    if summary.get("data_updated_at"):
        lines.append(f"資料時間：{summary['data_updated_at']}")

    events = summary.get("events") or []
    if not events:
        lines.append("")
        lines.append("目前**沒有任何報名紀錄或繳費紀錄**。")
    for e in events:
        lines.append("")
        title = e["sub_event"]
        if e.get("category"):
            title = f"{e['category']}／{title}"
        lines.append(f"#### {title}")
        if e.get("submitted_at"):
            lines.append(f"- 報名表送出時間：{e['submitted_at']}")
            lines.append(f"- 報名人數：{e.get('participant_count', 0)} 人")
            if e.get("participants"):
                lines.append("- 名單：")
                lines.extend(f"  {i + 1}. {p}" for i, p in enumerate(e["participants"]))
            if e.get("grand_total") is not None:
                lines.append(f"- 報名表總金額：NT$ {e['grand_total']:,}")
            if e.get("sponsor_tier"):
                lines.append(f"- 贊助：{e['sponsor_tier']}（NT$ {e.get('sponsor_amount', 0):,}）")
            if e.get("prize_sponsor_count"):
                lines.append(f"- 贊助獎：{e['prize_sponsor_count']} 筆（社友個人捐贈，不計入總金額）")
        else:
            lines.append("- 尚未送出報名表")
            if e.get("required_fee"):
                lines.append(f"- 本社應繳金額：NT$ {e['required_fee']:,}")
        p = e.get("payment") or {}
        lines.append(f"- 繳費狀態：{p.get('status_label', '❌ 未繳')}")
        if p.get("amount"):
            lines.append(f"  - 紀錄金額：NT$ {int(p['amount']):,}" + (f"，{p['method']}" if p.get("method") else "") + (f"，{p['date']}" if p.get("date") else ""))
        if p.get("status") == "NOTIFIED":
            detail = "、".join(x for x in [
                f"備註「{p['remit_note']}」" if p.get("remit_note") else "",
                f"金額 NT$ {int(p['remit_amount']):,}" if p.get("remit_amount") else "",
                f"日期 {p['remit_date']}" if p.get("remit_date") else "",
            ] if x)
            if detail:
                lines.append(f"  - 執秘回報：{detail}")

    if summary.get("bank_account"):
        lines.append("")
        lines.append(f"匯款帳號（全活動共用）：{summary['bank_account']}")
    if settings.SIGNUP_SITE_URL:
        lines.append("")
        lines.append(f"報名系統：{settings.SIGNUP_SITE_URL}")
    return "\n".join(lines)


async def execute_signup_registration_tool(
    user: AuthenticatedUser,
    requested_club_name: Optional[str] = None,
) -> dict:
    """
    工具入口。回傳 {ok, club_name, summary_markdown, source_card}。
    一般使用者：強制用登入社；管理員：可指定社名。
    """
    if user.is_admin and (requested_club_name or "").strip():
        club_name = requested_club_name.strip()
        scope_note = "地區管理員指定查詢"
    else:
        club_name = (user.club_name or "").strip()
        scope_note = "登入社本身"

    if not is_configured():
        md = "本地區尚未連接報名系統（未設定 SIGNUP_SUPABASE_URL），無法查詢報名與繳費狀態。請聯絡地區管理員。"
        return {"ok": False, "club_name": club_name, "summary_markdown": md, "source_card": None}

    if not club_name:
        md = "目前登入的帳號沒有所屬社，無法查詢報名狀態。"
        return {"ok": False, "club_name": club_name, "summary_markdown": md, "source_card": None}

    try:
        state = await fetch_signup_state()
    except Exception as e:  # 網路或權限錯誤，讓模型如實告知
        md = f"連線報名系統失敗（{type(e).__name__}），請稍後再試或直接到報名系統查看。"
        return {"ok": False, "club_name": club_name, "summary_markdown": md, "source_card": None}

    summary = summarize_club_registration(state or {}, club_name)
    md = format_club_registration_markdown(summary)
    source_card = {
        "filename": f"報名系統即時資料：{club_name}",
        "category": "本社報名與繳費查詢",
        "event_or_year": f"{len(summary['events'])} 個活動（{scope_note}）",
        "chunk_index": 0,
        "content": md,
        "similarity": 1.0,
        "match_type": "signup",
        "rerank_score": 1.0,
        "rerank_reason": "直接讀取報名系統資料庫（唯讀），非向量檢索",
    }
    return {"ok": True, "club_name": club_name, "summary_markdown": md, "source_card": source_card}
