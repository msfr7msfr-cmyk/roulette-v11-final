# -*- coding: utf-8 -*-
"""Roulette bot — V161 (Windows 150/180/210/240)."""
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
BOT_VERSION = "V161"
WINDOW_SIZE = 240 # تم تعديله ليتناسب مع أكبر نافذة
STREAK_THRESHOLD = 4
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

def generate_balance_report(history: list[int]) -> str:
    """
    نسب التوازن (أحمر/أسود) في نوافذ: 150 / 180 / 210 / 240 لفة.
    """
    if not history:
        return ""

    windows = [150, 180, 210, 240]

    def stats(seg: list[int]):
        r = sum(1 for n in seg if n in RED_NUMBERS)
        b = sum(1 for n in seg if n in BLACK_NUMBERS)
        total = len(seg)
        rp = (r / total * 100) if total else 0.0
        bp = (b / total * 100) if total else 0.0
        return r, b, rp, bp

    def label(dev: float) -> str:
        if abs(dev) < 3:
            return "⚖️ متوازن"
        if dev > 0:
            return f"🔴 أحمر +{dev:.1f}%"
        return f"⚫ أسود {dev:.1f}%"

    lines = ["⚖️ <b>نسب التوازن:</b>"]
    last_dev = None

    for w in windows:
        if len(history) < w:
            continue
        seg = history[-w:]
        r, b, rp, bp = stats(seg)
        dev = rp - 50.0
        last_dev = dev
        lines.append(
            f"<b>{w}</b>ل: 🔴{r}({rp:.1f}%) ⚫{b}({bp:.1f}%) | {label(dev)}"
        )

    if last_dev is None:
        seg = history
        r, b, rp, bp = stats(seg)
        dev = rp - 50.0
        last_dev = dev
        lines.append(
            f"<b>{len(seg)}</b>ل: 🔴{r}({rp:.1f}%) ⚫{b}({bp:.1f}%) | {label(dev)}"
        )

    if abs(last_dev) < 3:
        rec = "⚖️ اللونان متقاربان — لا أفضلية واضحة."
    elif last_dev > 0:
        rec = "💡 ⚫ الأسود أقل — مرشح للتعويض."
    else:
        rec = "💡 🔴 الأحمر أقل — مرشح للتعويض."

    lines.append("")
    lines.append(rec)

    return "\n".join(lines)

def analyze_streaks(history: list[int]) -> str:
    """
    يحلل تكرار السلاسل (Streaks) للأحمر والأسود في آخر 100 لفة.
    """
    if len(history) < 10:
        return ""

    recent = history[-100:] if len(history) >= 100 else history[:]
    
    colors = [get_color(n) for n in recent if get_color(n) in ("RED", "BLACK")]
    if len(colors) < 3:
        return ""

    streaks_red = Counter()
    streaks_black = Counter()

    current_color = colors[0]
    count = 1

    for c in colors[1:]:
        if c == current_color:
            count += 1
        else:
            if 3 <= count <= 10:
                if current_color == "RED":
                    streaks_red[count] += 1
                else:
                    streaks_black[count] += 1
            current_color = c
            count = 1

    if 3 <= count <= 10:
        if current_color == "RED":
            streaks_red[count] += 1
        else:
            streaks_black[count] += 1

    lines = ["🔥 <b>عدّاد السلاسل (آخر 100 لفة):</b>"]
    
    if not streaks_red and not streaks_black:
        lines.append("لا توجد سلاسل من 3 إلى 10 مرات.")
    else:
        if streaks_red:
            red_strs = " | ".join([f"{k} مرات: {v}" for k, v in sorted(streaks_red.items())])
            lines.append(f"🔴 أحمر: {red_strs}")
        if streaks_black:
            black_strs = " | ".join([f"{k} مرات: {v}" for k, v in sorted(streaks_black.items())])
            lines.append(f"⚫ أسود: {black_strs}")

    current_streak = 1
    for i in range(len(colors) - 2, -1, -1):
        if colors[i] == colors[-1]:
            current_streak += 1
        else:
            break
            
    last_color_ar = "🔴 أحمر" if colors[-1] == "RED" else "⚫ أسود"
    if current_streak >= 2:
        lines.append(f"⏳ <b>السلسلة الحالية:</b> {last_color_ar} ({current_streak} لفات)")

    return "\n".join(lines)

def analyze_high_low(history: list[int]) -> str:
    """
    يحلل الأرقام الكبيرة (19-36) والصغيرة (1-18) في نوافذ: 150 / 180 / 210 / 240 لفة.
    """
    if not history:
        return ""

    windows = [150, 180, 210, 240]
    lines = ["📏 <b>كبير / صغير:</b>"]
    
    last_big_pct = None

    for w in windows:
        if len(history) < w:
            continue
            
        recent = history[-w:]
        small_nums = [n for n in recent if 1 <= n <= 18]
        big_nums = [n for n in recent if 19 <= n <= 36]
        
        total = len(small_nums) + len(big_nums)
        if total == 0:
            continue

        small_pct = (len(small_nums) / total) * 100
        big_pct = (len(big_nums) / total) * 100
        last_big_pct = big_pct

        if abs(big_pct - 50) < 3:
            status = "⚖️ متوازن"
        elif big_pct > 50:
            status = "🔺 الكبير متقدم"
        else:
            status = "🔻 الصغير متقدم"

        lines.append(
            f"<b>{w}</b>ل: 🔺{len(big_nums)}({big_pct:.1f}%) 🔻{len(small_nums)}({small_pct:.1f}%) | {status}"
        )

    if last_big_pct is not None:
        lines.append("")
        if abs(last_big_pct - 50) < 3:
            rec = "⚖️ متوازن — لا أفضلية."
        elif last_big_pct > 50:
            rec = "💡 الصغير أقل — مرشح للتعويض."
        else:
            rec = "💡 الكبير أقل — مرشح للتعويض."
        lines.append(rec)

    return "\n".join(lines)

def get_hot_numbers_50(history: list[int]) -> str:
    """
    يحدد الجهة الأقوى (كبير أو صغير) في آخر 50 لفة، ويستخرج أقوى 4 أرقام.
    """
    if len(history) < 10:
        return ""

    recent = history[-50:] if len(history) >= 50 else history[:]
    
    small_nums = [n for n in recent if 1 <= n <= 18]
    big_nums = [n for n in recent if 19 <= n <= 36]
    
    total_colored = len(small_nums) + len(big_nums)
    if total_colored == 0:
        return ""

    big_pct = len(big_nums) / total_colored * 100
    small_pct = len(small_nums) / total_colored * 100

    if big_pct >= small_pct:
        target_side = "الكبير (19-36)"
        target_nums = big_nums
        icon = "🔺"
    else:
        target_side = "الصغير (1-18)"
        target_nums = small_nums
        icon = "🔻"

    if not target_nums:
        return "⚠️ لا توجد أرقام كافية في الجهة الأقوى."

    counter = Counter(target_nums)
    top_4 = counter.most_common(4)
    
    hot_list = [f"<b>{num}</b> ({cnt})" for num, cnt in top_4]

    lines = [f"🎯 <b>القناص (أقوى 4 أرقام في آخر 50 لفة):</b>"]
    lines.append(f"الجهة الأقوى: {icon} {target_side}")
    lines.append(f"الأرقام: {' | '.join(hot_list)}")
    
    return "\n".join(lines)

def generate_full_report(history: list[int]) -> str:
    if not history:
        return ""

    last_num = history[-1]
    color_ar = get_color_ar(get_color(last_num))

    report = f"🎯 <b>آخر رقم:</b> <b>{last_num}</b> ({color_ar})\n"
    report += f"📚 <b>السجل:</b> {len(history)} لفة\n"
    
    report += "\n" + generate_balance_report(history)
    report += "\n\n" + analyze_streaks(history)
    report += "\n\n" + analyze_high_low(history)
    report += "\n\n" + get_hot_numbers_50(history)

    return report

def analyze_strong_color(history: list[int]):
    if len(history) < 10:
        return "", None, False

    recent = history[-WINDOW_SIZE:] if len(history) >= WINDOW_SIZE else history[:]

    global_red = sum(1 for n in recent if n in RED_NUMBERS)
    global_black = sum(1 for n in recent if n in BLACK_NUMBERS)

    if global_red > global_black:
        strong_color, weak_color = "RED", "BLACK"
    elif global_black > global_red:
        strong_color, weak_color = "BLACK", "RED"
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
                f"🚨 <b>تنبيه القناص!</b> 🚨\n"
                f"انكسرت موجة {strong_ar} قوية ({strong_streak} لفات).\n"
                f"<b>العب على {strong_ar} الآن!</b>"
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
        f"• يحدد اللون القوي وينبهك عند انكسار موجة ({STREAK_THRESHOLD}+ لفات)\n"
        f"• نسب التوازن (أحمر/أسود) في نوافذ 150/180/210/240\n"
        f"• عدّاد السلاسل (Streaks) من 3 إلى 10 في آخر 100 لفة\n"
        f"• كبير/صغير في نوافذ 150/180/210/240\n"
        f"• القناص: أقوى 4 أرقام في آخر 50 لفة\n"
        f"• ينبهك إذا طاح الصفر\n\n"
        f"<b>الاستخدام:</b>\n"
        f"1) أرسل السجل كاملاً (10 أرقام أو أكثر)\n"
        f"2) بعدها كل لفة كرقم واحد\n\n"
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
        msg += "\n⏳ وضع المراقبة (أرسل كل لفة كرقم واحد)."

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
        msg += "\n\n⏳ وضع المراقبة. الشروط لم تتحقق بعد."

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

    # سجل كامل (10 أرقام أو أكثر) → تفعيل / إعادة تعيين
    if len(numbers) >= 10:
        handle_new_history(chat_id, numbers); return

    # رقم واحد → لفة جديدة
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
