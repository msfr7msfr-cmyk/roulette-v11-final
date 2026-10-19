# -*- coding: utf-8 -*-
"""Roulette bot — V47 (Fast Pulse: Top 3 numbers in last 30 spins)."""
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
BOT_VERSION = "V47"
WINDOW_SIZE = 30
PICK_N = 3
TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DB_FILE = os.getenv("DATABASE_PATH", "roulette.sqlite3")
PORT = int(os.getenv("PORT", "5000"))

app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("roulette_bot")
HTTP = requests.Session()

# ============ WHEEL ============
WHEEL_SIZE = 37
WHEEL_INDEX = {n: i for i, n in enumerate(range(37))}
PICK_EMOJI = ("🟢", "🔵", "🟡")

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
def pick_numbers(history: list[int], window: int = WINDOW_SIZE):
    """Find the top 3 most frequent numbers in the last 30 spins."""
    recent = history[-window:] if len(history) >= window else history[:]
    if not recent:
        return [], [], "empty"

    counts = Counter(recent)
    last_seen = {}
    for i, n in enumerate(recent):
        last_seen[n] = i

    all_nums = [n for n in range(WHEEL_SIZE) if counts.get(n, 0) > 0]
    
    # Sort by: count (desc), then recency (desc)
    all_nums.sort(key=lambda n: (-counts.get(n, 0), -last_seen.get(n, -1)))
    
    picked = all_nums[:PICK_N]
    picked_counts = [counts.get(n, 0) for n in picked]
    
    mode = f"Top {PICK_N} in last {len(recent)} spins"
    return picked, picked_counts, mode

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
                history    TEXT NOT NULL DEFAULT '[]',
                prediction TEXT NOT NULL DEFAULT '[]',
                hits       INTEGER NOT NULL DEFAULT 0,
                misses     INTEGER NOT NULL DEFAULT 0
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
    allowed = {"history", "prediction", "hits", "misses"}
    json_f = {"history", "prediction"}
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
            ON CONFLICT(chat_id) DO UPDATE SET
                history='[]', prediction='[]', hits=0, misses=0
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

def fmt_picks(picked: list[int], counts: list[int], window_len: int) -> str:
    if not picked:
        return "<i>لا توجد أرقام كافية بعد.</i>"
    lines = [f"<b>النافذة: آخر {window_len} لفة</b>", ""]
    for i, (n, c) in enumerate(zip(picked, counts)):
        emoji = PICK_EMOJI[i % len(PICK_EMOJI)]
        lines.append(f"{emoji} <b>{n}</b> — ظهر {c} مرات")
    return "\n".join(lines)

# ============ HANDLERS ============
def help_text() -> str:
    return (
        f"<b>بوت الروليت — {BOT_VERSION} (النبض السريع)</b>\n\n"
        f"المنطق:\n"
        f"• نافذة آخر <b>{WINDOW_SIZE}</b> لفة فقط\n"
        f"• يبحث عن الأرقام التي تتنفس الآن\n"
        f"• يعرض <b>أقوى {PICK_N} أرقام</b> فقط\n\n"
        f"طريقة الاستخدام:\n"
        f"1) أرسل سجلاً (30+ رقم) مرة واحدة.\n"
        f"2) سيعطيك الأرقام الثلاثة الأكثر سخونة.\n"
        f"3) بعد كل لفة، أرسل الرقم الجديد فقط.\n"
        f"4) البوت يحدّث القائمة تلقائياً.\n\n"
        f"/start /status /stats /help"
    )

def handle_new_history(chat_id: str, numbers: list[int]) -> None:
    picked, counts, mode = pick_numbers(numbers)
    save_user(chat_id, history=numbers, prediction=picked, hits=0, misses=0)
    send(
        chat_id,
        f"<b>{BOT_VERSION} — تم التفعيل</b>\n"
        f"السجل: <b>{len(numbers)}</b> رقم | آخر رقم: <b>{numbers[-1]}</b>\n\n"
        f"<b>الأرقام الثلاثة للرهان:</b>\n"
        f"{fmt_picks(picked, counts, min(len(numbers), WINDOW_SIZE))}",
    )

def handle_spin(chat_id: str, update_id: str, number: int) -> None:
    if not claim_update(update_id):
        send(chat_id, f"⚠️ {BOT_VERSION}: هذه الدورة سُجّلت مسبقاً.")
        return
    user = get_user(chat_id)
    history = json.loads(user["history"])
    if len(history) < 10:
        send(chat_id, f"⚠️ {BOT_VERSION}: أرسل السجل أولاً.")
        return
    prediction = json.loads(user["prediction"])
    hit = number in prediction
    history.append(number)
    new_picks, new_counts, mode = pick_numbers(history)
    hits = int(user["hits"]) + int(hit)
    misses = int(user["misses"]) + int(not hit)
    save_user(chat_id, history=history, prediction=new_picks,
              hits=hits, misses=misses)
    label = "✅ إصابة" if hit else "❌ خطأ"
    send(
        chat_id,
        f"<b>{BOT_VERSION} — {label}: {number}</b>\n\n"
        f"<b>الأرقام الثلاثة للدورة التالية:</b>\n"
        f"{fmt_picks(new_picks, new_counts, min(len(history), WINDOW_SIZE))}",
    )

def handle_status(chat_id: str, user: dict[str, Any], history: list[int]) -> None:
    if len(history) < 10:
        send(chat_id, f"{BOT_VERSION}: أرسل السجل أولاً.")
        return
    picked, counts, mode = pick_numbers(history)
    h, m = int(user["hits"]), int(user["misses"])
    ev = h + m
    rate = (h / ev * 100) if ev else 0.0
    send(
        chat_id,
        f"<b>{BOT_VERSION} — الحالة</b>\n"
        f"آخر رقم: <b>{history[-1]}</b>\n"
        f"إجمالي السجل: <b>{len(history)}</b>\n"
        f"الدقة: <b>{h}/{ev} ({rate:.1f}%)</b>\n\n"
        f"<b>الأرقام الثلاثة الحالية:</b>\n"
        f"{fmt_picks(picked, counts, min(len(history), WINDOW_SIZE))}",
    )

def handle_stats(chat_id: str, user: dict[str, Any]) -> None:
    h, m = int(user["hits"]), int(user["misses"])
    tot = h + m
    rate = (h / tot * 100) if tot else 0.0
    baseline = PICK_N / WHEEL_SIZE * 100
    send(
        chat_id,
        f"<b>{BOT_VERSION} — الإحصاءات</b>\n"
        f"اللفات: <b>{tot}</b> | إصابات: <b>{h}</b> | أخطاء: <b>{m}</b>\n"
        f"النسبة: <b>{rate:.1f}%</b>\n"
        f"خط الأساس العشوائي ({PICK_N} من 37): <b>{baseline:.2f}%</b>",
    )

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
    if text == "/stats":
        handle_stats(chat_id, user); return

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
        send(chat_id, f"{BOT_VERSION}: أرسل السجل أولاً (30 رقم على الأقل).")
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
