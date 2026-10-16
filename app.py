# -*- coding: utf-8 -*-
"""Roulette bot — V21 (clean, focused, color-coded)."""
from __future__ import annotations

import hmac
import html
import json
import logging
import math
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
BOT_VERSION = "V21"
TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DB_FILE = os.getenv("DATABASE_PATH", "roulette.sqlite3")
PORT = int(os.getenv("PORT", "5000"))

app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("roulette_bot")
HTTP = requests.Session()

# ============ WHEEL ============
WHEEL: tuple[int, ...] = (
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30,
    8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28,
    12, 35, 3, 26,
)
WHEEL_SIZE = 37
WHEEL_INDEX = {n: i for i, n in enumerate(WHEEL)}
MIN_HISTORY = 100
TOP_N = 20
BASELINE = TOP_N / WHEEL_SIZE
CHI2_95 = 50.998
CHI2_99 = 58.619

GROUP_EMOJI = ("🟢", "🔵", "🟡", "🔴")
GROUP_NAME  = ("المجموعة 1", "المجموعة 2", "المجموعة 3", "المجموعة 4")

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

# ============ SIGNAL 1: FREQUENCY ============
def _frequency_scores(history: list[int], halflife: float = 120.0,
                      prior_mass: float = 200.0) -> list[float]:
    n = len(history)
    if n == 0:
        return [1.0 / WHEEL_SIZE] * WHEEL_SIZE
    weights = [0.5 ** ((n - 1 - i) / halflife) for i in range(n)]
    counts = [0.0] * WHEEL_SIZE
    for num, w in zip(history, weights):
        counts[num] += w
    prior = prior_mass / WHEEL_SIZE
    denom = sum(counts) + prior_mass
    return [(c + prior) / denom for c in counts]

# ============ SIGNAL 2: BIAS ============
def _chi_square(history: list[int]) -> float:
    n = len(history)
    if n == 0:
        return 0.0
    counts = Counter(history)
    expected = n / WHEEL_SIZE
    return sum((counts.get(i, 0) - expected) ** 2 / expected
               for i in range(WHEEL_SIZE))

def _bias_strength(chi2: float, n: int) -> float:
    if n < 200:
        return 0.0
    if chi2 > 66.2:   return 1.00
    if chi2 > CHI2_99: return 0.75
    if chi2 > CHI2_95: return 0.50
    if chi2 > 43.0:    return 0.15
    return 0.0

def _top_sector(history: list[int], size: int = 7) -> list[int]:
    counts = Counter(history)
    best_members, best_total = None, -1
    for start in range(WHEEL_SIZE):
        members = [WHEEL[(start + o) % WHEEL_SIZE] for o in range(size)]
        total = sum(counts.get(m, 0) for m in members)
        if total > best_total:
            best_total, best_members = total, members
    return best_members or []

def _bias_scores(history: list[int], strength: float) -> list[float]:
    if strength <= 0:
        return [1.0 / WHEEL_SIZE] * WHEEL_SIZE
    sector = _top_sector(history, size=7)
    if not sector:
        return [1.0 / WHEEL_SIZE] * WHEEL_SIZE
    scores = [0.0] * WHEEL_SIZE
    for n in sector:
        scores[n] = 1.0 / len(sector)
    return scores

# ============ COMBINE ============
def _rank_numbers(history: list[int]) -> list[int]:
    freq = _frequency_scores(history, halflife=120, prior_mass=200.0)
    chi2 = _chi_square(history)
    strength = _bias_strength(chi2, len(history))
    if strength > 0:
        bias = _bias_scores(history, strength)
        bias_weight = min(0.60, strength * 0.60)
        combined = [(1 - bias_weight) * freq[n] + bias_weight * bias[n]
                    for n in range(WHEEL_SIZE)]
    else:
        combined = freq
    total = sum(combined)
    if total <= 0:
        combined = [1.0 / WHEEL_SIZE] * WHEEL_SIZE
    else:
        combined = [c / total for c in combined]
    return sorted(range(WHEEL_SIZE),
                  key=lambda n: (-combined[n], WHEEL_INDEX[n]))

def calculate_top20(history: list[int]):
    ranking = _rank_numbers(history)[:TOP_N]
    groups = [ranking[i:i+5] for i in range(0, TOP_N, 5)]
    return groups[0], groups[1], groups[2], groups[3], ranking

# ============ STATS ============
def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    r = successes / total
    z2 = z * z
    denom = 1 + z2 / total
    center = (r + z2 / (2 * total)) / denom
    margin = z * math.sqrt((r * (1 - r) + z2 / (4 * total)) / total) / denom
    return max(0.0, center - margin), min(1.0, center + margin)

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

def fmt(values: Sequence[int]) -> str:
    return html.escape("، ".join(str(v) for v in values))

def fmt_prediction(r: list[int]) -> str:
    groups = [r[i:i+5] for i in range(0, 20, 5)]
    lines = [f"<b>{BOT_VERSION}</b>", ""]
    for i, g in enumerate(groups):
        lines.append(f"{GROUP_EMOJI[i]} <b>{GROUP_NAME[i]}:</b> <code>{fmt(g)}</code>")
    return "\n".join(lines)

# ============ HANDLERS ============
def help_text() -> str:
    return (
        f"<b>بوت تحليل الروليت — {BOT_VERSION}</b>\n\n"
        "استراتيجية مركّزة:\n"
        "• تكرار موزون بالحداثة\n"
        "• كشف انحياز إحصائي (chi-square)\n\n"
        f"خط الأساس: <b>{BASELINE*100:.2f}%</b>\n\n"
        "🟢 المجموعة 1 | 🔵 المجموعة 2 | 🟡 المجموعة 3 | 🔴 المجموعة 4\n\n"
        "أرسل 100 رقم للتفعيل، ثم رقماً واحداً بعد كل دورة.\n\n"
        "/start /status /stats /bias /backtest /help"
    )

def handle_new_history(chat_id: str, numbers: list[int]) -> None:
    s1, s2, s3, s4, pred = calculate_top20(numbers)
    save_user(chat_id, history=numbers, prediction=pred, hits=0, misses=0)
    chi2 = _chi_square(numbers)
    strength = _bias_strength(chi2, len(numbers))
    bias_note = "لا" if strength == 0 else f"نعم ({strength:.0%})"
    send(
        chat_id,
        f"<b>{BOT_VERSION} — تم التفعيل</b>\n"
        f"السجل: <b>{len(numbers)}</b> | آخر رقم: <b>{numbers[-1]}</b>\n"
        f"chi² = <b>{chi2:.2f}</b> | انحياز: <b>{bias_note}</b>\n\n"
        f"<b>الأرقام العشرون:</b>\n{fmt_prediction(pred)}",
    )

def handle_spin(chat_id: str, update_id: str, number: int) -> None:
    if not claim_update(update_id):
        send(chat_id, f"⚠️ {BOT_VERSION}: هذه الدورة سُجّلت مسبقاً.")
        return
    user = get_user(chat_id)
    history = json.loads(user["history"])
    if len(history) < MIN_HISTORY:
        send(chat_id, f"⚠️ {BOT_VERSION}: أحتاج {MIN_HISTORY} رقماً على الأقل.")
        return
    prediction = json.loads(user["prediction"])
    hit = number in prediction
    history.append(number)
    s1, s2, s3, s4, new_pred = calculate_top20(history)
    hits = int(user["hits"]) + int(hit)
    misses = int(user["misses"]) + int(not hit)
    save_user(chat_id, history=history, prediction=new_pred,
              hits=hits, misses=misses)
    label = "✅ إصابة" if hit else "❌ خطأ"
    send(
        chat_id,
        f"<b>{BOT_VERSION} — {label}: {number}</b>\n\n"
        f"<b>الأرقام العشرون للدورة التالية:</b>\n{fmt_prediction(new_pred)}",
    )

def handle_status(chat_id: str, user: dict[str, Any], history: list[int]) -> None:
    if len(history) < MIN_HISTORY:
        send(chat_id, f"{BOT_VERSION}: أرسل {MIN_HISTORY} رقم على الأقل.")
        return
    s1, s2, s3, s4, pred = calculate_top20(history)
    h, m = int(user["hits"]), int(user["misses"])
    ev = h + m
    if ev:
        lo, hi = wilson(h, ev)
        measured = (f"الدقة: <b>{h}/{ev} ({h/ev*100:.1f}%)</b>\n"
                    f"CI 95%: <b>{lo*100:.1f}%–{hi*100:.1f}%</b>\n")
    else:
        measured = "لا نتائج مسجلة بعد.\n"
    chi2 = _chi_square(history)
    strength = _bias_strength(chi2, len(history))
    bias_note = "لا" if strength == 0 else f"نعم ({strength:.0%})"
    send(
        chat_id,
        f"<b>{BOT_VERSION} — الحالة</b>\n"
        f"آخر رقم: <b>{history[-1]}</b>\n"
        f"{measured}"
        f"chi² = <b>{chi2:.2f}</b> | انحياز: <b>{bias_note}</b>\n"
        f"خط الأساس: <b>{BASELINE*100:.2f}%</b>\n\n"
        f"<b>الأرقام العشرون:</b>\n{fmt_prediction(pred)}",
    )

def handle_stats(chat_id: str, user: dict[str, Any]) -> None:
    h, m = int(user["hits"]), int(user["misses"])
    tot = h + m
    if tot:
        rate = h / tot
        lo, hi = wilson(h, tot)
        conf = f"CI 95%: <b>{lo*100:.1f}%–{hi*100:.1f}%</b>\n"
    else:
        rate, conf = 0.0, ""
    send(
        chat_id,
        f"<b>{BOT_VERSION} — الإحصاءات</b>\n"
        f"اللفات: <b>{tot}</b> | إصابات: <b>{h}</b> | أخطاء: <b>{m}</b>\n"
        f"النسبة: <b>{rate*100:.1f}%</b>\n{conf}"
        f"خط الأساس: <b>{BASELINE*100:.2f}%</b>",
    )

def handle_bias(chat_id: str, history: list[int]) -> None:
    if len(history) < 100:
        send(chat_id, f"{BOT_VERSION}: أحتاج 100 رقم على الأقل.")
        return
    n = len(history)
    counts = Counter(history)
    chi2 = _chi_square(history)
    strength = _bias_strength(chi2, n)
    if chi2 > CHI2_99:
        verdict = "🔴 انحياز قوي (99%)"
    elif chi2 > CHI2_95:
        verdict = "🟠 انحياز معنوي (95%)"
    elif chi2 > 43.0:
        verdict = "🟡 انحياز طفيف"
    else:
        verdict = "🟢 لا انحياز معنوي"
    ranked = sorted(range(WHEEL_SIZE), key=lambda x: -counts.get(x, 0))
    hot = ranked[:5]; cold = ranked[-5:]
    hot_lines = "\n".join(f"  <b>{x}</b>: {counts.get(x,0)} ({counts.get(x,0)/n*100:.1f}%)" for x in hot)
    cold_lines = "\n".join(f"  <b>{x}</b>: {counts.get(x,0)} ({counts.get(x,0)/n*100:.1f}%)" for x in reversed(cold))
    sector = _top_sector(history, size=7)
    sector_total = sum(counts.get(x, 0) for x in sector)
    send(
        chat_id,
        f"<b>{BOT_VERSION} — فحص الانحياز</b>\n"
        f"العينة: <b>{n}</b>\n"
        f"chi² = <b>{chi2:.2f}</b> (df=36)\n"
        f"قوة الإشارة: <b>{strength:.0%}</b>\n\n"
        f"{verdict}\n\n"
        f"<b>الأكثر ظهوراً:</b>\n{hot_lines}\n\n"
        f"<b>الأقل ظهوراً:</b>\n{cold_lines}\n\n"
        f"<b>القطاع الساخن:</b>\n  {fmt(sector)}\n"
        f"  إجمالي: <b>{sector_total}</b> من {n} ({sector_total/n*100:.1f}%)",
    )

def handle_backtest(chat_id: str, history: list[int]) -> None:
    if len(history) < MIN_HISTORY + 30:
        send(chat_id, f"{BOT_VERSION}: أحتاج {MIN_HISTORY + 30} رقماً على الأقل.")
        return
    sample = min(200, len(history) - MIN_HISTORY)
    hits = 0
    start = len(history) - sample
    for ti in range(start, len(history)):
        prefix = history[:ti]
        chosen = set(_rank_numbers(prefix)[:TOP_N])
        if history[ti] in chosen:
            hits += 1
    lo, hi = wilson(hits, sample)
    diff = (hits / sample - BASELINE) * 100
    sig = "نعم" if lo > BASELINE else "لا"
    send(
        chat_id,
        f"<b>{BOT_VERSION} — اختبار متدرّج</b>\n"
        f"اللفات: <b>{sample}</b> | إصابات: <b>{hits}</b>\n"
        f"الدقة: <b>{hits/sample*100:.1f}%</b>\n"
        f"خط الأساس: <b>{BASELINE*100:.2f}%</b>\n"
        f"الفرق: <b>{diff:+.1f} نقطة</b>\n"
        f"CI 95%: <b>{lo*100:.1f}%–{hi*100:.1f}%</b>\n"
        f"تفوّق معنوي: <b>{sig}</b>",
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
    if text == "/bias":
        handle_bias(chat_id, history); return
    if text == "/backtest":
        handle_backtest(chat_id, history); return
    try:
        numbers = parse_numbers(text)
    except ValueError as e:
        send(chat_id, f"⚠️ {BOT_VERSION}: {html.escape(str(e))}"); return
    if not numbers:
        return
    if len(numbers) >= MIN_HISTORY:
        handle_new_history(chat_id, numbers); return
    if len(history) < MIN_HISTORY:
        send(chat_id, f"{BOT_VERSION}: وصلني {len(numbers)}. أرسل {MIN_HISTORY} رقم للبدء.")
        return
    if len(numbers) != 1:
        send(chat_id, f"{BOT_VERSION}: أرسل رقماً واحداً فقط.")
        return
    handle_spin(chat_id, update_id, numbers[0])

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
