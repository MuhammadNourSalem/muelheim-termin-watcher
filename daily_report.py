"""
تقرير يومي - مراقب مواعيد Ausländeramt مولهايم
================================================
يُشغَّل مرة واحدة يومياً (الساعة 00:00) عبر workflow منفصل.
يقرأ سجل تشغيلات اليوم من run_log.json، يحسب عدد التشغيلات ومعدل
الفاصل الزمني بينها، يرسل تقرير تيليجرام، ثم يصفّر السجل ليوم جديد.
"""

import json
import os
from datetime import datetime

import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
RUN_LOG_FILE = "run_log.json"


def send_telegram(message: str):
    base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    requests.post(
        f"{base}/sendMessage",
        data={"chat_id": TELEGRAM_CHAT_ID, "text": message},
        timeout=15,
    )


def main():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise SystemExit("❌ TELEGRAM_BOT_TOKEN أو TELEGRAM_CHAT_ID غير موجودين كمتغيرات بيئة.")

    try:
        with open(RUN_LOG_FILE, "r", encoding="utf-8") as f:
            runs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        runs = []

    count = len(runs)

    if count == 0:
        message = (
            "📊 التقرير اليومي - مراقب مواعيد Ausländeramt\n\n"
            "⚠️ لم يُسجَّل أي تشغيل خلال اليوم الماضي.\n"
            "قد يشير هذا لمشكلة بالجدولة - راجع تبويب Actions."
        )
    else:
        timestamps = [datetime.fromisoformat(r["timestamp"]) for r in runs]
        timestamps.sort()

        if count >= 2:
            gaps_minutes = [
                (timestamps[i + 1] - timestamps[i]).total_seconds() / 60
                for i in range(len(timestamps) - 1)
            ]
            avg_gap = sum(gaps_minutes) / len(gaps_minutes)
            min_gap = min(gaps_minutes)
            max_gap = max(gaps_minutes)
            gap_info = (
                f"⏱️ متوسط الفاصل الزمني: {avg_gap:.1f} دقيقة\n"
                f"⏱️ أقصر فاصل: {min_gap:.1f} دقيقة\n"
                f"⏱️ أطول فاصل: {max_gap:.1f} دقيقة\n"
            )
        else:
            gap_info = "⏱️ تشغيل واحد فقط، لا يمكن حساب فاصل زمني.\n"

        errors_count = sum(1 for r in runs if r.get("available") is False and "error" in r)
        first_run = timestamps[0].strftime("%H:%M:%S")
        last_run = timestamps[-1].strftime("%H:%M:%S")

        message = (
            "📊 التقرير اليومي - مراقب مواعيد Ausländeramt\n\n"
            f"🟢 السكربت شغال بنجاح\n"
            f"🔢 عدد مرات التشغيل اليوم: {count}\n"
            f"{gap_info}"
            f"🕐 أول تشغيل: {first_run}\n"
            f"🕐 آخر تشغيل: {last_run}\n\n"
            "لا داعي لأي إجراء منك، هذا فقط تأكيد أن كل شيء يعمل."
        )

    send_telegram(message)

    # تصفير السجل ليوم جديد
    with open(RUN_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)


if __name__ == "__main__":
    main()
