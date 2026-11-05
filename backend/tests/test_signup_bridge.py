"""
signup_bridge 純函式測試：用假資料驗證「某社報名與繳費摘要」的整理邏輯。
執行：backend/venv/bin/python backend/tests/test_signup_bridge.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.signup_bridge import (  # noqa: E402
    format_club_registration_markdown,
    summarize_club_registration,
)

FAKE_STATE = {
    "divisionsData": [
        {"id": 1, "name": "第一分區", "clubs": [{"name": "測試甲社"}, {"name": "測試乙社"}]},
    ],
    "categoriesData": [
        {"id": "sports", "name": "⚽ 運動賽事", "subEvents": ["2. 地區保齡球聯誼賽"]},
        {"id": "seminars", "name": "📘 研討會及講習會", "subEvents": ["1. 獎助金管理研討會 (GMS)"]},
    ],
    "chairConfig": {
        "bankAccount": "上海商銀 123-456",
        "feeApportionment": 10000,
        "subEventFees": {"seminars::1. 獎助金管理研討會 (GMS)": {"feeApportionment": 12000}},
    },
    "registrationOrders": {
        "2. 地區保齡球聯誼賽": [
            {
                "clubName": "測試甲社",
                "submittedAt": "2026-11-01 10:00",
                "grandTotal": 3000,
                "items": [
                    {"role": "社長", "nickname": "Tony", "name": "王假名", "type": "參賽", "diet": "葷"},
                    {"role": "", "nickname": "", "name": "李假名", "type": "只用餐", "diet": "素", "veganNote": "蛋奶素"},
                ],
                "prizeSponsors": [{"name": "王假名", "type": "cash", "amount": 2000}],
            },
            {"clubName": "測試乙社", "submittedAt": "2026-11-02 09:00", "grandTotal": 1500, "items": [{"name": "別社的人"}]},
        ]
    },
    "chairPaymentRecords": {
        "sports::2. 地區保齡球聯誼賽": {
            "測試甲社": {"status": "NOTIFIED", "amount": 3000, "remitNote": "甲社保齡球", "remitAmount": 3000, "remitDate": "2026-11-03"},
            "測試乙社": {"status": "PAID_MANUAL", "amount": 1500},
        },
        "seminars::1. 獎助金管理研討會 (GMS)": {
            "測試甲社": {"status": "PAID_EMAIL", "amount": 12000, "method": "銀行匯款", "date": "2026-10-20"},
        },
    },
    "lastUpdated": "2026-11-05T01:00:00Z",
}


def check(cond, msg):
    print(("✅ " if cond else "❌ ") + msg)
    if not cond:
        raise SystemExit(1)


s = summarize_club_registration(FAKE_STATE, "測試甲社")
check(s["division"] == "第一分區", "分區正確")
check(len(s["events"]) == 2, "甲社有 2 個活動（1 個報名表 + 1 個只有繳費紀錄）")
bowling = next(e for e in s["events"] if "保齡球" in e["sub_event"])
check(bowling["participant_count"] == 2, "保齡球報名 2 人")
check("王假名" in bowling["participants"][0] and "別社的人" not in str(s), "名單只含本社，沒有別社的人")
check(bowling["payment"]["status"] == "NOTIFIED" and not bowling["payment"]["is_paid"], "保齡球狀態 NOTIFIED 視為未繳")
gms = next(e for e in s["events"] if "GMS" in e["sub_event"])
check(gms.get("submitted_at") is None and gms["required_fee"] == 12000, "GMS 沒報名表、應繳金額取子活動設定 12000")
check(gms["payment"]["is_paid"], "GMS 已繳")

md = format_club_registration_markdown(s)
check("蛋奶素" in md and "差點" not in md, "Markdown 含葷素備註")
check("上海商銀" in md, "Markdown 含匯款帳號")

empty = summarize_club_registration(FAKE_STATE, "沒報名的社")
check(empty["events"] == [], "沒報名的社回空清單")
check("沒有任何報名紀錄" in format_club_registration_markdown(empty), "空清單的文字明確說沒有")
print("\n全部通過")
