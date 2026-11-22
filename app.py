# -*- coding: utf-8 -*-
"""Roulette bot — V261 (Strongest Color: Escape Dozen/Column 3 to 5 times)."""
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
from collections import Counter
from typing import Any

import requests
from flask import Flask, abort, request

# ============ CONFIG ============
BOT_VERSION = "V261"
TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DB_FILE = os.getenv("DATABASE_PATH", "roulette.sqlite3")
PORT = int(os.getenv("PORT", "5000"))

app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("roulette_bot")
HTTP = requests.Session()

# ============ WHEEL & CATEGORIES ============
WHEEL_SIZE = 37
WHEEL_INDEX = {n: i for i, n in enumerate(range(37))}
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
BLACK_NUMBERS = {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}

def get_color(n: int):
    if n in RED_NUMBERS: return "RED"
    if n in BLACK_NUMBERS: return "BLACK"
    return "ZERO"

def get_dozen(n: int) -> int:
    if 1 <= n <= 12: return 1
    if 13 <= n <= 24: return 2
    if 25 <= n <= 36: return 3
    return 0

def get_column(n: int) -> int:
    if n == 0: return 0
    if n % 3 == 1: return 1
    if n % 3 == 2: return 2
    return 3

def get_color_ar(c: str) -> str:
    if c == "RED": return "🔴 أحمر"
    if c == "BLACK": return "⚫ أسود"
    return ""

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
            if not 0 <= n <= 36:
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
def get_strongest_color(history: list[int]) -> str:
    recent = history[-250:] if len(history) >= 250 else history[:]
    reds = sum(1 for n in recent if n in RED_NUMBERS)
    blacks = sum(1 for n in recent if n in BLACK_NUMBERS)
    if reds >= blacks:
        return "RED"
    return "BLACK"

def analyze_strongest_color_escape(history: list[int]) -> str:
    if len(history) < 10:
        return "⏳ السجل صغير جداً."

    recent = history[-250:] if len(history) >= 250 else history[:]
    last_num = history[-1]
    strongest_color = get_strongest_color(history)
    strongest_ar = get_color_ar(strongest_color)

    # قواميس لتخزين عدد الهروب لكل رقم
    escape_dozen = Counter()
    escape_column = Counter()

    for i in range(len(recent) - 1):
        num = recent[i]
        next_num = recent[i+1]
        
        if num == 0 or next_num == 0: continue
        
        # نبحث فقط في أرقام اللون الأقوى
        if get_color(num) != strongest_color: continue
            
        # هل هرب من المربع؟
        if get_dozen(num) != get_dozen(next_num):
            escape_dozen[num] += 1
            
        # هل هرب من العمود؟
        if get_column(num) != get_column(next_num):
            escape_column[num] += 1

    lines = [f"🔥 <b>اللون الأقوى حالياً: {strongest_ar}</b>"]
    lines.append(f"🎯 <b>أرقام {strongest_ar} التي تهرب (من 3 إلى 5 مرات):</b>")
    
    has_data = False
    
    # نجمع كل الأرقام التي حققت الشروط
    all_nums = set(escape_dozen.keys()) | set(escape_column.keys())
    
    for num in sorted(all_nums):
        d_esc = escape_dozen[num]
        c_esc = escape_column[num]
        
        # التحقق من شرط الـ 3 إلى 5
        d_ok = 3 <= d_esc <= 5
        c_ok = 3 <= c_esc <= 5
        
        if d_ok or c_ok:
            has_data = True
            num_str = str(num)
            if num == last_num:
                num_str = f"<b>🟢 {num_str}</b> (طاح الآن)"
                
            details = []
            if d_ok:
                details.append(f"هروب من المربع {d_esc} مرات")
            if c_ok:
                details.append(f"هروب من العمود {c_esc} مرات")
                
            lines.append(f"• الرقم <b>{num_str}</b>: (" + " | ".join(details) + ")")

    if not has_data:
        return "\n".join(lines) + "\n❌ لا توجد أرقام تطابق الشروط حالياً (تحتاج 3 إلى 5 مرات)."

    return "\n".join(lines)

# ============ DATABASE ============
def connect_db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_FILE, timeout=20)
    c.row_factory = sqlite3.Row
    return c

def init_db() -> None:
    with connect_db() as c:
        c.execute("PRAGMA journal_mode=WAL;")
        c.executescript("""
            CREATE TABLE IF NOT EXISTS users (chat_id TEXT PRIMARY KEY, history TEXT NOT NULL DEFAULT '[]');
            CREATE TABLE IF NOT EXISTS updates_seen (update_id TEXT PRIMARY KEY, ts INTEGER NOT NULL);
        """)
        c.execute("DELETE FROM updates_seen WHERE ts < ?", (int(time.time()) - 7 * 86400,))

def get_user(chat_id: str) -> dict[str, Any]:
    with connect_db() as c:
        row = c.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        if row is None:
            c.execute("INSERT INTO users(chat_id) VALUES(?)", (str(chat_id),))
            c.commit()
            row = c.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        return dict(row)

def save_user(chat_id: str, **vals: Any) -> None:
    allowed = {"history"}
    json_f = {"history"}
    fields, params = [], []
    for k, v in vals.items():
        if k not in allowed: continue
        if k in json_f: v = json.dumps(v, ensure_ascii=False)
        fields.append(f"{k}=?"); params.append(v)
    if not fields: return
    params.append(str(chat_id))
    with connect_db() as c:
        c.execute(f"UPDATE users SET {', '.join(fields)} WHERE chat_id=?", params)

def reset_user(chat_id: str) -> None:
    with connect_db() as c:
        c.execute("INSERT INTO users(chat_id) VALUES(?) ON CONFLICT(chat_id) DO UPDATE SET history='[]'", (str(chat_id),))

def claim_update(update_id: str) -> bool:
    with connect_db() as c:
        try:
            c.execute("INSERT INTO updates_seen(update_id, ts) VALUES(?, ?)", (str(update_id), int(time.time())))
            return True
        except sqlite3.IntegrityError:
            return False

# ============ TELEGRAM ============
def send(chat_id: str, text: str) -> bool:
    if not TOKEN: return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True, "parse_mode": "HTML"}
    try:
        r = HTTP.post(url, json=payload, timeout=15)
        if r.ok: return True
        err = ""
        try: err = r.json().get("description", "")
        except: pass
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
        f"• يحدد اللون الأقوى في آخر 250 لفة.\n"
        f"• يبحث عن أرقام هذا اللون التي تهرب من المربع أو العمود.\n"
        f"• يعرض الأرقام التي تكرر معها الهروب من 3 إلى 5 مرات.\n"
        f"• يضع علامة 🟢 على الرقم الذي طاح للتو.\n\n"
        f"<b>الاستخدام:</b>\n"
        f"1) أرسل السجل كاملاً (10 أرقام أو أكثر)\n"
        f"2) بعدها كل لفة كرقم واحد\n\n"
        f"/start /status /help"
    )

def handle_new_history(chat_id: str, numbers: list[int]) -> None:
    save_user(chat_id, history=numbers)
    send_reports(chat_id, numbers, is_new=True)

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
    send_reports(chat_id, history, is_new=False, last_num=number)

def send_reports(chat_id: str, history: list[int], is_new: bool, last_num: int = None):
    prefix = f"<b>{BOT_VERSION} — {'تم التفعيل' if is_new else f'اللفة: {last_num}'}</b>\n"
    prefix += f"📚 <b>إجمالي الأرقام المسجلة:</b> {len(history)} لفة\n"
    
    if last_num is not None and last_num == 0: 
        prefix += "\n🟢 <b>تنبيه:</b> الرقم صفر (0) طاح للتو!"
    
    send(chat_id, prefix)

    report = analyze_strongest_color_escape(history)
    if report: 
        send(chat_id, report)

def handle_status(chat_id: str, user: dict[str, Any], history: list[int]) -> None:
    if len(history) < 10:
        send(chat_id, f"{BOT_VERSION}: أرسل السجل أولاً.")
        return
    send_reports(chat_id, history, is_new=False, last_num=history[-1])

# ============ ROUTER ============
def process(message: dict[str, Any], update_id: str) -> None:
    chat = message.get("chat")
    if not isinstance(chat, dict) or "id" not in chat: return
    chat_id = str(chat["id"])
    text = (message.get("text") or "").strip()
    if not text: return

    if text in ("/start", "/help"):
        if text == "/start": reset_user(chat_id)
        send(chat_id, help_text()); return

    user = get_user(chat_id)
    history = json.loads(user["history"])

    if text == "/status": handle_status(chat_id, user, history); return

    try: numbers = parse_numbers(text)
    except ValueError as e: send(chat_id, f"⚠️ {BOT_VERSION}: {html.escape(str(e))}"); return

    if not numbers: return

    if len(numbers) >= 10: handle_new_history(chat_id, numbers); return

    if len(numbers) == 1:
        if len(history) < 10:
            send(chat_id, f"{BOT_VERSION}: أرسل السجل أولاً (10 أرقام على الأقل).")
            return
        handle_spin(chat_id, update_id, numbers[0]); return

    send(chat_id, f"{BOT_VERSION}: أرسل رقماً واحداً، أو سجلاً كاملاً للبدء.")

# ============ WEBHOOK ============
@app.get("/")
def home() -> tuple[str, int]: return f"ok {BOT_VERSION}", 200

@app.post("/telegram-webhook")
def webhook() -> tuple[str, int]:
    if WEBHOOK_SECRET:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(token, WEBHOOK_SECRET): abort(403)
    update = request.get_json(silent=True)
    if not isinstance(update, dict): return "ok", 200
    msg = update.get("message")
    if not isinstance(msg, dict): return "ok", 200
    uid = str(update.get("update_id") or secrets.token_hex(8))
    try: process(msg, uid)
    except Exception: log.exception("handler error")
    return "ok", 200

init_db()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
