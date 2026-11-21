# -*- coding: utf-8 -*-
"""Roulette bot — V253 (Triplets Max Absence in 250 Spins)."""
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
BOT_VERSION = "V253"
TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DB_FILE = os.getenv("DATABASE_PATH", "roulette.sqlite3")
PORT = int(os.getenv("PORT", "5000"))

app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("roulette_bot")
HTTP = requests.Session()

# ============ GROUPS ============
TRIPLETS = {
    "المجموعة 1 (1, 2, 3)": {1, 2, 3},
    "المجموعة 2 (4, 5, 6)": {4, 5, 6},
    "المجموعة 3 (7, 8, 9)": {7, 8, 9},
    "المجموعة 4 (10, 11, 12)": {10, 11, 12},
    "المجموعة 5 (13, 14, 15)": {13, 14, 15},
    "المجموعة 6 (16, 17, 18)": {16, 17, 18},
    "المجموعة 7 (19, 20, 21)": {19, 20, 21},
    "المجموعة 8 (22, 23, 24)": {22, 23, 24},
    "المجموعة 9 (25, 26, 27)": {25, 26, 27},
    "المجموعة 10 (28, 29, 30)": {28, 29, 30},
    "المجموعة 11 (31, 32, 33)": {31, 32, 33},
    "المجموعة 12 (34, 35, 36)": {34, 35, 36},
}

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
def analyze_triplets_absence(history: list[int]) -> str:
    """
    يحسب أطول فترة غياب لكل مجموعة (أرقام متجاورة) في آخر 250 لفة.
    """
    if not history:
        return "⏳ السجل فارغ."

    recent = history[-250:] if len(history) >= 250 else history[:]
    last_num = history[-1]

    results = []
    
    for name, triplet in TRIPLETS.items():
        max_absence = 0
        current_absence = 0
        last_seen = "لم تظهر"
        
        for i, num in enumerate(recent):
            if num in triplet:
                if current_absence > max_absence:
                    max_absence = current_absence
                current_absence = 0
                # نحسب رقم اللفة الحقيقي في السجل الكلي
                real_spin_idx = len(history) - len(recent) + i + 1
                last_seen = f"اللفة {real_spin_idx}"
            else:
                current_absence += 1
                
        # التحقق من الفترة الأخيرة (بعد آخر ظهور)
        if current_absence > max_absence:
            max_absence = current_absence
            
        # إذا لم تظهر أبداً في الـ 250 لفة
        if last_seen == "لم تظهر":
            max_absence = len(recent)

        # إضافة علامة 🟢 إذا كان آخر رقم طاح ينتمي لهذه المجموعة
        is_current = " 🟢" if last_num in triplet else ""
        
        results.append((max_absence, f"• <b>{name}</b>{is_current}: غابت حتى <b>{max_absence}</b> لفة متتالية."))

    # ترتيب النتائج تنازلياً حسب أطول غياب
    results.sort(key=lambda x: x[0], reverse=True)

    lines = ["📊 <b>أطول فترات غياب للمجموعات في آخر 250 لفة:</b>"]
    lines.extend([r[1] for r in results])

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
        f"• يراقب 12 مجموعة من الأرقام (ثلاثيات متجاورة).\n"
        f"• يحسب أطول فترة غياب لكل مجموعة في آخر 250 لفة.\n"
        f"• يضع علامة 🟢 على المجموعة التي ظهر منها آخر رقم.\n\n"
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

    report = analyze_triplets_absence(history)
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
