# -*- coding: utf-8 -*-
"""Roulette bot — V200 (Streak Timeline & Distance within 300 spins)."""
from __future__ import annotations

import hmac
import html
import json
import logging
import os
import re
import secrets
import sqlite3
import time
import unicodedata
from typing import Any

import requests
from flask import Flask, abort, request

# ============ CONFIG ============
BOT_VERSION = "V200"
LOOKBACK_WINDOW = 300 # نطاق البحث (آخر 300 لفة)
TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DB_FILE = os.getenv("DATABASE_PATH", "roulette.sqlite3")
PORT = int(os.getenv("PORT", "5000"))

app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("roulette_bot")
HTTP = requests.Session()

# ============ WHEEL & COLORS ============
WHEEL_SIZE = 37
WHEEL_INDEX = {n: i for i, n in enumerate(range(37))}
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
BLACK_NUMBERS = {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}

# ============ PARSING ============
def parse_numbers(text: str) -> list[int]:
    normalized = "".join(
        str(unicodedata.decimal(c)) if c.isdecimal() else c for c in text
    ).strip()
    tokens = [t for t in re.split(r"[\s,;،؛|]+", normalized) if t]
    nums: list[int] = []
    for token in tokens:
        if re.fullmatch(r"\d{1,2}", token):
            n = int(token)
            if n not in WHEEL_INDEX:
                raise ValueError(f"الرقم {n} خارج النطاق (0-36)")
            nums.append(n)
            continue
        if re.fullmatch(r"\d{3,}", token):
            i, chunk, ok = 0, [], True
            while i < len(token):
                two = token[i:i+2]
                if len(two) == 2 and int(two) <= 36:
                    chunk.append(int(two)); i += 2
                elif int(token[i]) <= 36:
                    chunk.append(int(token[i])); i += 1
                else:
                    ok = False; break
            if ok and chunk:
                nums.extend(chunk); continue
        raise ValueError(f"خطأ في الرمز: {token}")
    return nums

# ============ CORE LOGIC ============
def get_color(n: int):
    if n in RED_NUMBERS: return "RED"
    if n in BLACK_NUMBERS: return "BLACK"
    return "ZERO"

def get_color_ar(color_code: str):
    if color_code == "RED": return "🔴 الأحمر"
    if color_code == "BLACK": return "⚫ الأسود"
    return "🟢 الصفر"

def analyze_streaks_timeline(history: list[int]) -> str:
    """
    يحلل السلاسل الحالية (مرتين أو 3 مرات) ويبحث عن تاريخها
    والمسافة بينها وبين السلاسل السابقة في آخر 300 لفة.
    """
    if len(history) < 5:
        return "⏳ السجل صغير جداً لتحليل السلاسل."

    # نأخذ آخر 300 لفة فقط
    recent = history[-LOOKBACK_WINDOW:]
    
    # تحويل الألوان فقط (بدون الصفر)
    colors = [get_color(n) for n in recent if get_color(n) in ("RED", "BLACK")]
    if len(colors) < 3:
        return "⏳ لا توجد ألوان كافية لتحليل السلاسل."

    # 1. حساب السلسلة الحالية (التي تنتهي بآخر لفة)
    current_color = colors[-1]
    current_streak_len = 0
    for c in reversed(colors):
        if c == current_color:
            current_streak_len += 1
        else:
            break

    color_ar = get_color_ar(current_color)

    # إذا كانت السلسلة الحالية 1، لا نطبع شيئاً (لأنها لم تصل لمرتين)
    if current_streak_len < 2:
        return f"⏳ السلسلة الحالية: {color_ar} (1 لفة) — ننتظر التكرار."
    if current_streak_len > 3:
        return f"⚠️ السلسلة الحالية: {color_ar} ({current_streak_len} لفات) — تجاوزت 3، ننتظر الانكسار."

    lines = [f"🔥 <b>السلسلة الحالية: {color_ar} ({current_streak_len} لفات)</b>"]

    # 2. البحث عن السلاسل السابقة بنفس الطول ونفس اللون
    # نمشي على السجل من البداية (داخل الـ 300) ونستخرج كل السلاسل
    streaks_found = [] # قائمة تحتوي على (index_in_colors, streak_length)
    
    i = 0
    while i < len(colors) - 1:
        c = colors[i]
        length = 1
        while i + length < len(colors) and colors[i + length] == c:
            length += 1
        
        # نأخذ السلاسل السابقة فقط (التي لا تكون هي السلسلة الحالية في النهاية)
        # ونفس اللون ونفس الطول المطلوب
        if c == current_color and length == current_streak_len:
            # التأكد أن هذه ليست السلسلة الحالية (التي في النهاية)
            if i + length < len(colors):
                streaks_found.append(i + length - 1) # نحفظ موقع آخر لفة في السلسلة
        
        i += length

    if not streaks_found:
        lines.append(f"❌ لم تحدث سلسلة {color_ar} ({current_streak_len} لفات) في آخر {len(recent)} لفة سابقة.")
        return "\n".join(lines)

    # 3. حساب المسافات والتواريخ
    # السلسلة الحالية تنتهي عند colors[-1] (أي في موقع len(colors)-1)
    current_end_idx = len(colors) - 1
    
    # نحسب المسافة من آخر لفة في كل سلسلة سابقة إلى أول لفة في السلسلة الحالية
    # ملاحظة: المسافة = عدد اللفات بينهما (بدون احتساب لفات السلسلة نفسها أو السابقة)
    
    lines.append(f"🔍 <b>تاريخ السلاسل في آخر {len(recent)} لفة:</b>")

    # نعكس القائمة لنجعل الأحدث أولاً
    streaks_found.reverse()

    for idx, prev_end_idx in enumerate(streaks_found):
        # المسافة بين آخر لفة في السلسلة السابقة وأول لفة في السلسلة الحالية
        current_start_idx = current_end_idx - current_streak_len + 1
        
        # الفرق بين بداية السلسلة الحالية ونهاية السلسلة السابقة
        # نطرح 1 لأننا لا نحسب لفة السابقة نفسها
        distance = current_start_idx - prev_end_idx - 1
        
        # معرفة رقم اللفة داخل الـ 300 (أو داخل السجل كله)
        # لأننا قد نكون أخذنا 300 فقط، نحسب الموقع الحقيقي
        real_hist_idx = len(history) - len(recent) + prev_end_idx
        real_spin_number = real_hist_idx + 1 # +1 لأن الترقيم يبدأ من 1

        if idx == 0:
            lines.append(f"• <b>آخر سلسلة سابقة:</b>")
        else:
            lines.append(f"• <b>سلسلة سابقة {idx+1}:</b>")
            
        lines.append(f"  - انتهت في اللفة رقم: <b>{real_spin_number}</b>")
        
        if distance == 0:
            lines.append(f"  - المسافة: <b>مباشرة بعدها</b> (0 لفة).")
        else:
            lines.append(f"  - المسافة: <b>قبل {distance} لفة</b> من بداية السلسلة الحالية.")

    return "\n".join(lines)

def generate_full_report(history: list[int]) -> str:
    if not history:
        return ""

    last_num = history[-1]
    color_ar = get_color_ar(get_color(last_num))

    report = f"🎯 <b>آخر رقم:</b> <b>{last_num}</b> ({color_ar})\n"
    report += f"📚 <b>السجل:</b> {len(history)} لفة\n\n"
    
    # قسم تحليل السلاسل الزمني
    report += analyze_streaks_timeline(history)

    return report

# ============ DATABASE ============
def connect_db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_FILE, timeout=20)
    c.row_factory = sqlite3.Row
    return c

def init_db() -> None:
    with connect_db() as c:
        c.execute("PRAGMA journal_mode=WAL;")
        c.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id    TEXT PRIMARY KEY,
                history    TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS updates_seen (
                update_id TEXT PRIMARY KEY,
                ts        INTEGER NOT NULL
            );
        """)
        c.execute("DELETE FROM updates_seen WHERE ts < ?",
                  (int(time.time()) - 7 * 86400,))

def get_user(chat_id: str) -> dict[str, Any]:
    with connect_db() as c:
        row = c.execute("SELECT * FROM users WHERE chat_id=?",
                        (str(chat_id),)).fetchone()
        if row is None:
            c.execute("INSERT INTO users(chat_id) VALUES(?)", (str(chat_id),))
            c.commit()
            row = c.execute("SELECT * FROM users WHERE chat_id=?",
                            (str(chat_id),)).fetchone()
        return dict(row)

def save_user(chat_id: str, **vals: Any) -> None:
    allowed = {"history"}
    json_f = {"history"}
    fields, params = [], []
    for k, v in vals.items():
        if k not in allowed:
            continue
        if k in json_f:
            v = json.dumps(v, ensure_ascii=False)
        fields.append(f"{k}=?")
        params.append(v)
    if not fields:
        return
    params.append(str(chat_id))
    with connect_db() as c:
        c.execute(f"UPDATE users SET {', '.join(fields)} WHERE chat_id=?", params)

def reset_user(chat_id: str) -> None:
    with connect_db() as c:
        c.execute("""
            INSERT INTO users(chat_id) VALUES(?)
            ON CONFLICT(chat_id) DO UPDATE SET history='[]'
        """, (str(chat_id),))

def claim_update(update_id: str) -> bool:
    with connect_db() as c:
        try:
            c.execute("INSERT INTO updates_seen(update_id, ts) VALUES(?, ?)",
                      (str(update_id), int(time.time())))
            return True
        except sqlite3.IntegrityError:
            return False

# ============ TELEGRAM ============
def send(chat_id: str, text: str) -> bool:
    if not TOKEN:
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text,
               "disable_web_page_preview": True, "parse_mode": "HTML"}
    try:
        r = HTTP.post(url, json=payload, timeout=15)
        if r.ok:
            return True
        err = ""
        try:
            err = r.json().get("description", "")
        except Exception:
            pass
        log.warning(f"send failed: status={r.status_code} desc={err}")
        if "parse" in err.lower() or "entities" in err.lower() or "tag" in err.lower():
            payload.pop("parse_mode", None)
            return HTTP.post(url, json=payload, timeout=15).ok
        return False
    except requests.RequestException:
        log.exception("send failed")
        return False

# ============ HANDLERS ============
def help_text() -> str:
    return (
        f"<b>بوت الروليت — {BOT_VERSION}</b>\n\n"
        f"• يعرض السلسلة الحالية (أحمر/أسود) إذا تكررت مرتين أو 3 مرات.\n"
        f"• يبحث في آخر {LOOKBACK_WINDOW} لفة عن السلاسل السابقة المشابهة.\n"
        f"• يعرض رقم اللفة التي انتهت فيها السلسلة السابقة.\n"
        f"• يحسب المسافة (باللفات) بين السلسلة السابقة وبداية السلسلة الحالية.\n"
        f"• ينبهك إذا طاح الصفر.\n\n"
        f"<b>الاستخدام:</b>\n"
        f"1) أرسل السجل كاملاً (10 أرقام أو أكثر)\n"
        f"2) بعدها كل لفة كرقم واحد\n\n"
        f"/start /status /help"
    )

def handle_new_history(chat_id: str, numbers: list[int]) -> None:
    save_user(chat_id, history=numbers)

    report = generate_full_report(numbers)
    msg = f"<b>{BOT_VERSION} — تم التفعيل</b>\n\n{report}\n"
    send(chat_id, msg)

def handle_spin(chat_id: str, update_id: str, number: int) -> None:
    if not claim_update(update_id):
        send(chat_id, f"⚠️ {BOT_VERSION}: هذه الدورة سُجّلت مسبقاً.")
        return
    user = get_user(chat_id)
    history = json.loads(user["history"])

    if len(history) < 10:
        send(chat_id, f"⚠️ {BOT_VERSION}: أرسل السجل أولاً.")
        return

    history.append(number)
    save_user(chat_id, history=history)

    report = generate_full_report(history)
    msg = f"<b>{BOT_VERSION} — اللفة: {number}</b>\n\n{report}"

    if number == 0:
        msg += "\n\n🟢 <b>تنبيه:</b> الرقم صفر (0) طاح للتو!"

    send(chat_id, msg)

def handle_status(chat_id: str, user: dict[str, Any], history: list[int]) -> None:
    if len(history) < 10:
        send(chat_id, f"{BOT_VERSION}: أرسل السجل أولاً.")
        return

    report = generate_full_report(history)
    msg = f"<b>{BOT_VERSION} — الحالة</b>\n\n{report}"
    send(chat_id, msg)

# ============ ROUTER ============
def process(message: dict[str, Any], update_id: str) -> None:
    chat = message.get("chat")
    if not isinstance(chat, dict) or "id" not in chat:
        return
    chat_id = str(chat["id"])
    text = (message.get("text") or "").strip()
    if not text:
        return

    if text in ("/start", "/help"):
        if text == "/start":
            reset_user(chat_id)
        send(chat_id, help_text())
        return

    user = get_user(chat_id)
    history = json.loads(user["history"])

    if text == "/status":
        handle_status(chat_id, user, history); return

    try:
        numbers = parse_numbers(text)
    except ValueError as e:
        send(chat_id, f"⚠️ {BOT_VERSION}: {html.escape(str(e))}"); return

    if not numbers:
        return

    if len(numbers) >= 10:
        handle_new_history(chat_id, numbers); return

    if len(numbers) == 1:
        if len(history) < 10:
            send(chat_id, f"{BOT_VERSION}: أرسل السجل أولاً (10 أرقام على الأقل).")
            return
        handle_spin(chat_id, update_id, numbers[0]); return

    send(chat_id, f"{BOT_VERSION}: أرسل رقماً واحداً، أو سجلاً كاملاً للبدء.")

# ============ WEBHOOK ============
@app.get("/")
def home() -> tuple[str, int]:
    return f"ok {BOT_VERSION}", 200

@app.post("/telegram-webhook")
def webhook() -> tuple[str, int]:
    if WEBHOOK_SECRET:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(token, WEBHOOK_SECRET):
            abort(403)
    update = request.get_json(silent=True)
    if not isinstance(update, dict):
        return "ok", 200
    msg = update.get("message")
    if not isinstance(msg, dict):
        return "ok", 200
    uid = str(update.get("update_id") or secrets.token_hex(8))
    try:
        process(msg, uid)
    except Exception:
        log.exception("handler error")
    return "ok", 200

init_db()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
