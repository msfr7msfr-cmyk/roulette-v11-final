# -*- coding: utf-8 -*-
"""Roulette bot — V149 (Strong Sniper + Full Report + Zero Alert)."""
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
from collections.abc import Sequence
from typing import Any

import requests
from flask import Flask, abort, request

# ============ CONFIG ============
BOT_VERSION = "V149"
WINDOW_SIZE = 200
STREAK_THRESHOLD = 3
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

def generate_full_report(history: list[int]):
    recent = history[-WINDOW_SIZE:] if len(history) >= WINDOW_SIZE else history[:]
    total = len(recent)
    red_count = sum(1 for n in recent if n in RED_NUMBERS)
    black_count = sum(1 for n in recent if n in BLACK_NUMBERS)
    zero_count = sum(1 for n in recent if n == 0)
    last_num = recent[-1]
    
    red_pct = (red_count / total) * 100 if total else 0
    black_pct = (black_count / total) * 100 if total else 0
    zero_pct = (zero_count / total) * 100 if total else 0

    report = f"📊 <b>تقرير شامل (آخر {total} لفة):</b>\n"
    report += f"🔴 الأحمر: <b>{red_count}</b> مرة (<b>{red_pct:.1f}%</b>)\n"
    report += f"⚫ الأسود: <b>{black_count}</b> مرة (<b>{black_pct:.1f}%</b>)\n"
    report += f"🟢 الصفر: <b>{zero_count}</b> مرة (<b>{zero_pct:.1f}%</b>)\n"
    report += f"🎯 <b>آخر رقم طاح:</b> {last_num}\n"
    
    return report

def analyze_strong_color(history: list[int]):
    if len(history) < 10:
        return "", None, False

    recent = history[-WINDOW_SIZE:] if len(history) >= WINDOW_SIZE else history[:]
    
    # اللون القوي
    global_red = sum(1 for n in recent if n in RED_NUMBERS)
    global_black = sum(1 for n in recent if n in BLACK_NUMBERS)
    
    if global_red > global_black:
        strong_color = "RED"
        weak_color = "BLACK"
    elif global_black > global_red:
        strong_color = "BLACK"
        weak_color = "RED"
    else:
        return "", None, False

    last_color = get_color(recent[-1])
    
    if last_color == weak_color:
        strong_streak = 0
        for n in reversed(recent[:-1]): 
            if get_color(n) == strong_color:
                strong_streak += 1
            else:
                break
                
        if strong_streak >= STREAK_THRESHOLD:
            strong_ar = get_color_ar(strong_color)
            alert_msg = (
                f"🚨 <b>تنبيه القناص (اللون القوي)!</b> 🚨\n\n"
                f"انكسرت موجة {strong_ar} قوية ({strong_streak} لفات).\n"
                f"<b>العملية: العب على {strong_ar} الآن (لأنه سيعود)!</b>"
            )
            return alert_msg, strong_color, True
            
    return "", None, False


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
        payload.pop("parse_mode", None)
        return HTTP.post(url, json=payload, timeout=15).ok
    except requests.RequestException:
        log.exception("send failed")
        return False


# ============ HANDLERS ============
def help_text() -> str:
    return (
        f"<b>بوت الروليت — {BOT_VERSION}</b>\n\n"
        f"المنطق:\n"
        f"• يحدد اللون القوي وينبهك عند انكساره (القناص)\n"
        f"• يعرض تقريراً شاملاً بالنسب وعدد الصفر وآخر رقم\n"
        f"• ينبهك إذا طاح الصفر\n\n"
        f"/start /status /help"
    )


def handle_new_history(chat_id: str, numbers: list[int]) -> None:
    save_user(chat_id, history=numbers)
    
    report = generate_full_report(numbers)
    msg = f"<b>{BOT_VERSION} — تم التفعيل</b>\n\n{report}\n"
    
    alert_msg, color, is_alert = analyze_strong_color(numbers)
    if is_alert:
        msg += f"\n{alert_msg}"
    else:
        msg += "\n⏳ البوت في وضع المراقبة (لن يرسل شيئاً حتى تتحقق الشروط)."
        
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
    
    # تنبيه الصفر
    if number == 0:
        msg += "\n\n🟢 <b>تنبيه:</b> الرقم صفر (0) طاح للتو!"
        
    # تنبيه القنص
    alert_msg, new_color, is_alert = analyze_strong_color(history)
    if is_alert:
        msg += f"\n\n{alert_msg}"
        
    send(chat_id, msg)


def handle_status(chat_id: str, user: dict[str, Any], history: list[int]) -> None:
    if len(history) < 10:
        send(chat_id, f"{BOT_VERSION}: أرسل السجل أولاً.")
        return
    
    report = generate_full_report(history)
    msg = f"<b>{BOT_VERSION} — الحالة</b>\n\n{report}"
    
    alert_msg, color, is_alert = analyze_strong_color(history)
    if is_alert:
        msg += f"\n\n{alert_msg}"
    else:
        msg += "\n\n⏳ البوت في وضع المراقبة. الشروط لم تتحقق بعد."
        
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
    if len(numbers) == 1 and len(history) >= 10:
        handle_spin(chat_id, update_id, numbers[0]); return
    if len(numbers) == 1 and len(history) < 10:
        send(chat_id, f"{BOT_VERSION}: أرسل السجل أولاً (10 أرقام على الأقل).")
        return
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
