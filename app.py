# -*- coding: utf-8 -*-
"""Conservative walk-forward roulette bot — optimized single file.

Truth: roulette is random. This bot never predicts the next number.
It ranks 37 numbers by historical heuristics and returns top-20.
Expected long-run hit rate: 20/37 ≈ 54.05% (baseline).
Any deviation beyond Wilson 95% CI is noise.
"""
from __future__ import annotations

import functools
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
TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DB_FILE = os.getenv("DATABASE_PATH", "roulette.sqlite3")
PORT = int(os.getenv("PORT", "5000"))

app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("roulette_bot")
HTTP = requests.Session()
if not WEBHOOK_SECRET:
    log.warning("WEBHOOK_SECRET is unset — webhook endpoint is unprotected")

# ============ WHEEL MODEL ============
WHEEL: tuple[int, ...] = (
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30,
    8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28,
    12, 35, 3, 26,
)
WHEEL_SIZE = len(WHEEL)  # 37
WHEEL_INDEX = {n: i for i, n in enumerate(WHEEL)}
MIN_HISTORY = 100
MIN_BACKTEST_SPINS = 30
TOP_N = 20
RANDOM_TOP20_RATE = TOP_N / WHEEL_SIZE  # ≈ 0.5405

UNIFORM: tuple[float, ...] = tuple(1.0 / WHEEL_SIZE for _ in range(WHEEL_SIZE))

# ============ VALIDATION ============
def _validated(history: Sequence[int]) -> list[int]:
    values = list(history)
    for v in values:
        if type(v) is not int or v not in WHEEL_INDEX:
            raise ValueError("history must contain only integers 0..36")
    return values

def parse_numbers(text: str) -> list[int]:
    """Parse whitespace/comma separated numbers. Accepts Arabic-Indic digits.

    Also handles a run of glued digits by greedily splitting into valid 1-2 digit
    values in 0..36 (e.g. '5734' -> [5,7,34]). Ambiguous by design but safer
    than silently mis-parsing.
    """
    normalized = "".join(
        str(unicodedata.decimal(c)) if c.isdecimal() else c for c in text
    ).strip()

    tokens = [t for t in re.split(r"[\s,;،؛|]+", normalized) if t]
    nums: list[int] = []

    for token in tokens:
        if re.fullmatch(r"\d{1,2}", token):
            n = int(token)
            if n not in WHEEL_INDEX:
                raise ValueError(f"الرقم {n} خارج نطاق الروليت (0-36)")
            nums.append(n)
            continue

        # glued digit run: greedy split into 1-2 digit numbers
        if re.fullmatch(r"\d{3,}", token):
            i, chunk = 0, []
            ok = True
            while i < len(token):
                two = token[i : i + 2]
                if len(two) == 2 and int(two) <= 36:
                    chunk.append(int(two))
                    i += 2
                elif int(token[i]) <= 36:
                    chunk.append(int(token[i]))
                    i += 1
                else:
                    ok = False
                    break
            if ok and chunk:
                nums.extend(chunk)
                continue

        raise ValueError(f"خطأ في الرمز: {token}")

    return nums

# ============ GEOMETRY ============
def wheel_step(a: int, b: int) -> int:
    s = (WHEEL_INDEX[b] - WHEEL_INDEX[a]) % WHEEL_SIZE
    return s - WHEEL_SIZE if s > WHEEL_SIZE // 2 else s

def neighbors(center: int, radius: int = 2) -> list[int]:
    idx = WHEEL_INDEX[center]
    return [WHEEL[(idx + o) % WHEEL_SIZE] for o in range(-radius, radius + 1)]

# ============ MATH HELPERS ============
def _normalize(values: Sequence[float]) -> list[float]:
    total = sum(values)
    if not math.isfinite(total) or total <= 0:
        return list(UNIFORM)
    return [max(0.0, v) / total for v in values]

def _decay_weights(count: int, halflife: float) -> list[float]:
    if count <= 0:
        return []
    if halflife <= 0:
        raise ValueError("halflife must be positive")
    return [0.5 ** ((count - 1 - i) / halflife) for i in range(count)]

# ============ EXPERTS ============
@functools.lru_cache(maxsize=1)
def _expert_names() -> tuple[str, ...]:
    return ("uniform", "recent", "long", "decay", "near1", "near2", "step", "sector")

def _expert_scores(history: tuple[int, ...]) -> dict[str, list[float]]:
    """Compute all expert forecasts. history is a tuple for cache key safety."""
    values = _validated(history)
    if not values:
        return {name: list(UNIFORM) for name in _expert_names()}

    n1 = _score_neighbor_affinity(values, radius=1)
    n2 = _score_neighbor_affinity(values, radius=2)

    return {
        "uniform": list(UNIFORM),
        "recent": _score_frequency(values, lookback=70, prior_mass=75.0),
        "long": _score_frequency(values, lookback=350, prior_mass=100.0),
        "decay": _score_frequency(values, lookback=180, halflife=55.0, prior_mass=90.0),
        "near1": n1,
        "near2": n2,
        "step": _score_step_distribution(values),
        "sector": _score_hot_sectors(values),
    }

def _score_frequency(history, lookback=250, halflife=None, prior_mass=80.0):
    recent = history[-max(0, lookback):] if lookback else []
    weights = _decay_weights(len(recent), halflife) if halflife else [1.0] * len(recent)
    counts = [0.0] * WHEEL_SIZE
    for n, w in zip(recent, weights):
        counts[n] += w
    prior = prior_mass / WHEEL_SIZE
    denom = sum(counts) + prior_mass
    if denom <= 0:
        return list(UNIFORM)
    return [(c + prior) / denom for c in counts]

def _score_neighbor_affinity(history, radius: int = 2, lookback: int = 120):
    recent = history[-lookback:]
    if not recent:
        return list(UNIFORM)
    weights = _decay_weights(len(recent), 35.0)
    width = 2 * radius + 1
    act = [0.0] * WHEEL_SIZE
    for n, w in zip(recent, weights):
        for c in neighbors(n, radius):
            act[c] += w / width
    prior = 90.0 / WHEEL_SIZE
    return _normalize([v + prior for v in act])

def _score_step_distribution(history, lookback=250):
    if len(history) < 25:
        return list(UNIFORM)
    recent = history[-lookback:]
    steps = [wheel_step(recent[i - 1], recent[i]) for i in range(1, len(recent))]
    counts = Counter(steps)
    prior = 110.0 / WHEEL_SIZE
    last = history[-1]
    return _normalize([counts.get(wheel_step(last, c), 0) + prior for c in range(WHEEL_SIZE)])

def _score_hot_sectors(history, lookback=120, sector_size=5):
    if not history:
        return list(UNIFORM)
    radius = max(0, sector_size // 2)
    recent = history[-lookback:]
    weights = _decay_weights(len(recent), 40.0)
    act = [0.0] * WHEEL_SIZE
    width = 2 * radius + 1
    for n, w in zip(recent, weights):
        for c in neighbors(n, radius):
            act[c] += w / width
    prior = 100.0 / WHEEL_SIZE
    return _normalize([v + prior for v in act])

# ============ MODEL COMBINATION ============
def _combine_scores(history: Sequence[int]) -> list[float]:
    """Weighted ensemble. Weights are FIXED and honest — no fake 'learning'.

    Rationale: on a random process, adaptive weighting = overfitting.
    A fixed prior that mildly favors neighborhood/step structure is the
    most defensible choice. uniform gets a healthy floor so the ensemble
    never drifts far from baseline.
    """
    experts = _expert_scores(tuple(history))
    weights = {
        "uniform": 0.30,
        "recent":  0.10,
        "long":    0.08,
        "decay":   0.12,
        "near1":   0.12,
        "near2":   0.10,
        "step":    0.10,
        "sector":  0.08,
    }
    total_w = sum(weights.values())
    combined = [0.0] * WHEEL_SIZE
    for name, forecast in experts.items():
        w = weights[name] / total_w
        for n in range(WHEEL_SIZE):
            combined[n] += w * forecast[n]
    return _normalize(combined)

def _select_top20(scores: Sequence[float], top_n: int = TOP_N) -> list[int]:
    if len(scores) != WHEEL_SIZE:
        raise ValueError("scores must contain 37 values")
    return sorted(
        range(WHEEL_SIZE),
        key=lambda n: (-scores[n], WHEEL_INDEX[n]),
    )[:top_n]

def calculate_v23(history: Sequence[int]) -> tuple[list[int], list[int], list[int], list[int], list[int]]:
    values = _validated(history)
    ranking = _select_top20(_combine_scores(values))
    groups = [ranking[i:i + 5] for i in range(0, TOP_N, 5)]
    return groups[0], groups[1], groups[2], groups[3], ranking

# ============ STATISTICS ============
def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    rate = successes / total
    z2 = z * z
    denom = 1 + z2 / total
    center = (rate + z2 / (2 * total)) / denom
    margin = z * math.sqrt((rate * (1 - rate) + z2 / (4 * total)) / total) / denom
    return max(0.0, center - margin), min(1.0, center + margin)

def _backtest_accuracy(history, top_n: int = TOP_N, test_len: int = 200):
    """Walk-forward backtest with honest prefix-only forecasting.

    Optimized: reuses each prefix's expert forecasts. Still O(test_len * cost)
    but cost per step is small because we avoid recomputing weights.
    """
    values = _validated(history)
    available = len(values) - MIN_HISTORY
    sample = min(test_len, available)
    if sample < MIN_BACKTEST_SPINS:
        return None
    hits = 0
    start = len(values) - sample
    for ti in range(start, len(values)):
        prefix = values[:ti]
        chosen = set(_select_top20(_combine_scores(prefix), top_n=top_n))
        if values[ti] in chosen:
            hits += 1
    lo, hi = wilson_interval(hits, sample)
    baseline = top_n / WHEEL_SIZE
    return {
        "hits": hits,
        "trials": sample,
        "rate": hits / sample,
        "baseline": baseline,
        "ci_low": lo,
        "ci_high": hi,
        "above_baseline_significant": lo > baseline,
    }

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
                chat_id     TEXT PRIMARY KEY,
                history     TEXT NOT NULL DEFAULT '[]',
                sec1        TEXT NOT NULL DEFAULT '[]',
                sec2        TEXT NOT NULL DEFAULT '[]',
                sec3        TEXT NOT NULL DEFAULT '[]',
                sec4        TEXT NOT NULL DEFAULT '[]',
                prediction  TEXT NOT NULL DEFAULT '[]',
                hits        INTEGER NOT NULL DEFAULT 0,
                misses      INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS updates_seen (
                update_id TEXT PRIMARY KEY,
                ts        INTEGER NOT NULL
            );
        """)
        # auto-prune stale update ids (older than 7 days)
        c.execute("DELETE FROM updates_seen WHERE ts < ?", (int(time.time()) - 7 * 86400,))

def get_user(chat_id: str) -> dict[str, Any]:
    with connect_db() as c:
        row = c.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        if row is None:
            c.execute("INSERT INTO users(chat_id) VALUES(?)", (str(chat_id),))
            c.commit()
            row = c.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        return dict(row)

_ALLOWED_FIELDS = {
    "history", "sec1", "sec2", "sec3", "sec4", "prediction",
    "hits", "misses",
}
_JSON_FIELDS = {"history", "sec1", "sec2", "sec3", "sec4", "prediction"}

def save_user(chat_id: str, **values: Any) -> None:
    fields, params = [], []
    for k, v in values.items():
        if k not in _ALLOWED_FIELDS:
            continue
        if k in _JSON_FIELDS:
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
                history='[]', sec1='[]', sec2='[]', sec3='[]', sec4='[]',
                prediction='[]', hits=0, misses=0
        """, (str(chat_id),))

def claim_update(update_id: str) -> bool:
    """Atomically claim an update_id. Returns True if newly claimed."""
    with connect_db() as c:
        try:
            c.execute(
                "INSERT INTO updates_seen(update_id, ts) VALUES(?, ?)",
                (str(update_id), int(time.time())),
            )
            return True
        except sqlite3.IntegrityError:
            return False

# ============ TELEGRAM ============
def send_message(chat_id: str, text: str) -> bool:
    if not TOKEN:
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
        "parse_mode": "HTML",
    }
    try:
        r = HTTP.post(url, json=payload, timeout=15)
        if r.ok:
            return True
        payload.pop("parse_mode", None)
        return HTTP.post(url, json=payload, timeout=15).ok
    except requests.RequestException:
        log.exception("Unable to send Telegram message.")
        return False

def _format_list(values: Sequence[int]) -> str:
    return html.escape("، ".join(str(v) for v in values))

# ============ HANDLERS ============
def help_message() -> str:
    return (
        "<b>بوت تحليل الروليت</b>\n\n"
        "يرتّب الأرقام الـ37 وفق حِكَم إحصائية (تكرارات مموّهة، جوار على العجلة، "
        "توزيع خطوات، كثافة قطاعات) ثم يعرض أعلى 20.\n"
        "<b>الحقيقة:</b> الروليت العادل عشوائي. المتوقع على المدى الطويل "
        f"<b>{RANDOM_TOP20_RATE*100:.2f}%</b> — أي نفس نسبة أي اختيار عشوائي لعشرين رقماً.\n"
        "أي انحراف كبير في عيّنة صغيرة هو ضوضاء.\n\n"
        "1. أرسل سجلاً من 100 رقم على الأقل (يقبل الأرقام العربية والفارسية).\n"
        "2. بعدها أرسل رقماً واحداً بعد كل دورة.\n\n"
        "/start - مسح والبدء من جديد\n"
        "/status - القائمة الحالية\n"
        "/stats - إحصاءاتك مقابل خط الأساس\n"
        "/backtest - اختبار متدرّج صادق\n"
        "/help - هذه الرسالة"
    )

def _format_prediction(s1, s2, s3, s4) -> str:
    return (
        f"المجموعة 1: <code>{_format_list(s1)}</code>\n"
        f"المجموعة 2: <code>{_format_list(s2)}</code>\n"
        f"المجموعة 3: <code>{_format_list(s3)}</code>\n"
        f"المجموعة 4: <code>{_format_list(s4)}</code>"
    )

def _handle_new_history(chat_id: str, numbers: list[int]) -> None:
    s1, s2, s3, s4, pred = calculate_v23(numbers)
    save_user(
        chat_id,
        history=numbers,
        sec1=s1, sec2=s2, sec3=s3, sec4=s4,
        prediction=pred,
        hits=0, misses=0,
    )
    send_message(
        chat_id,
        f"<b>تم تسجيل السجل وتفعيل التحليل</b>\n"
        f"حجم السجل: <b>{len(numbers)}</b> | آخر رقم: <b>{numbers[-1]}</b>\n"
        f"خط الأساس: <b>{RANDOM_TOP20_RATE*100:.2f}%</b>\n"
        f"<i>هذه أول قائمة؛ لا تُقيّم دقتها قبل تسجيل دورات لاحقة.</i>\n\n"
        f"{_format_prediction(s1, s2, s3, s4)}",
    )

def _handle_single_spin(chat_id: str, update_id: str, number: int) -> None:
    if not claim_update(update_id):
        send_message(chat_id, "⚠️ هذه الدورة سُجّلت مسبقاً.")
        return

    user = get_user(chat_id)
    history = json.loads(user["history"])
    if len(history) < MIN_HISTORY:
        send_message(chat_id, f"⚠️ أحتاج {MIN_HISTORY} رقماً على الأقل قبل تسجيل الدورات.")
        return

    prediction = json.loads(user["prediction"])
    hit = number in prediction

    history.append(number)
    s1, s2, s3, s4, new_pred = calculate_v23(history)
    hits = int(user["hits"]) + int(hit)
    misses = int(user["misses"]) + int(not hit)

    save_user(
        chat_id,
        history=history,
        sec1=s1, sec2=s2, sec3=s3, sec4=s4,
        prediction=new_pred,
        hits=hits, misses=misses,
    )

    label = "✅ إصابة" if hit else "❌ لم تصب"
    send_message(
        chat_id,
        f"<b>{label}: {number}</b>\n\n"
        f"<b>الأرقام العشرون للدورة التالية:</b>\n"
        f"{_format_prediction(s1, s2, s3, s4)}",
    )

def _handle_status(chat_id: str, user: dict[str, Any], history: list[int]) -> None:
    if len(history) < MIN_HISTORY:
        send_message(chat_id, f"أرسل سجلاً من {MIN_HISTORY} رقم على الأقل لتفعيل التوقعات.")
        return
    s1, s2, s3, s4, pred = calculate_v23(history)
    h, m = int(user["hits"]), int(user["misses"])
    ev = h + m
    if ev:
        lo, hi = wilson_interval(h, ev)
        measured = (
            f"الدقة المسجلة: <b>{h}/{ev} ({h/ev*100:.1f}%)</b>\n"
            f"فاصل الثقة 95%: <b>{lo*100:.1f}%–{hi*100:.1f}%</b>\n"
        )
    else:
        measured = "لم تُسجّل نتائج كافية بعد.\n"
    send_message(
        chat_id,
        f"<b>الأرقام العشرون الحالية</b>\n"
        f"آخر رقم: <b>{history[-1]}</b>\n"
        f"{measured}"
        f"خط الأساس: <b>{RANDOM_TOP20_RATE*100:.2f}%</b>\n"
        f"<i>الروليت عشوائي؛ لا يوجد ما يضمن النتيجة القادمة.</i>\n\n"
        f"{_format_prediction(s1, s2, s3, s4)}",
    )

def _handle_stats(chat_id: str, user: dict[str, Any]) -> None:
    h, m = int(user["hits"]), int(user["misses"])
    tot = h + m
    if tot:
        rate = h / tot
        lo, hi = wilson_interval(h, tot)
        conf = f"فاصل الثقة 95%: <b>{lo*100:.1f}%–{hi*100:.1f}%</b>\n"
    else:
        rate, conf = 0.0, ""
    send_message(
        chat_id,
        f"<b>الإحصاءات الفعلية</b>\n"
        f"اللفات المقيمة: <b>{tot}</b> | إصابات: <b>{h}</b> | إخفاقات: <b>{m}</b>\n"
        f"نسبة الإصابة: <b>{rate*100:.1f}%</b>\n{conf}"
        f"خط الأساس: <b>{RANDOM_TOP20_RATE*100:.2f}%</b>\n"
        f"<i>العينة القصيرة قد تبدو أعلى أو أقل من مستواها الحقيقي.</i>",
    )

def _handle_backtest(chat_id: str, history: list[int]) -> None:
    res = _backtest_accuracy(history, top_n=TOP_N, test_len=200)
    if res is None:
        send_message(
            chat_id,
            f"أحتاج {MIN_HISTORY + MIN_BACKTEST_SPINS} رقماً على الأقل "
            f"({MIN_HISTORY} للتدريب + {MIN_BACKTEST_SPINS}+ للاختبار).",
        )
        return
    diff = (res["rate"] - res["baseline"]) * 100
    concl = (
        "الحد الأدنى لفاصل الثقة تجاوز خط الأساس — لكن هذا قد يحدث بالحظ."
        if res["above_baseline_significant"]
        else "لا يثبت هذا الاختبار تفوّقاً على العشوائي."
    )
    send_message(
        chat_id,
        f"<b>اختبار متدرّج صادق</b>\n"
        f"اللفات المختبرة: <b>{res['trials']}</b> | الإصابات: <b>{res['hits']}</b>\n"
        f"الدقة: <b>{res['rate']*100:.1f}%</b>\n"
        f"خط الأساس: <b>{res['baseline']*100:.2f}%</b>\n"
        f"الفرق: <b>{diff:+.1f} نقطة مئوية</b>\n"
        f"فاصل الثقة 95%: <b>{res['ci_low']*100:.1f}%–{res['ci_high']*100:.1f}%</b>\n"
        f"<i>{concl} النتائج الماضية لا تضمن المستقبل.</i>",
    )

def process_message(message: dict[str, Any], update_id: str) -> None:
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
        send_message(chat_id, help_message())
        return

    user = get_user(chat_id)
    history = json.loads(user["history"])

    if text == "/status":
        _handle_status(chat_id, user, history)
        return
    if text == "/stats":
        _handle_stats(chat_id, user)
        return
    if text == "/backtest":
        _handle_backtest(chat_id, history)
        return

    try:
        numbers = parse_numbers(text)
    except ValueError as e:
        send_message(chat_id, f"⚠️ {html.escape(str(e))}")
        return

    if not numbers:
        return

    if len(numbers) >= MIN_HISTORY:
        _handle_new_history(chat_id, numbers)
        return

    if len(history) < MIN_HISTORY:
        send_message(
            chat_id,
            f"وصلني {len(numbers)} رقماً. أرسل سجلاً من {MIN_HISTORY} رقم على الأقل للبدء.",
        )
        return

    if len(numbers) != 1:
        send_message(chat_id, "أرسل رقماً واحداً فقط بعد تفعيل التحليل.")
        return

    _handle_single_spin(chat_id, update_id, numbers[0])

# ============ WEBHOOK ============
@app.get("/")
def home() -> tuple[str, int]:
    return "Roulette analysis bot is running.", 200

@app.post("/telegram-webhook")
def webhook() -> tuple[str, int]:
    if WEBHOOK_SECRET:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(token, WEBHOOK_SECRET):
            abort(403)
    update = request.get_json(silent=True)
    if not isinstance(update, dict):
        return "ok", 200
    message = update.get("message")
    if not isinstance(message, dict):
        return "ok", 200
    update_id = str(update.get("update_id") or secrets.token_hex(8))
    try:
        process_message(message, update_id)
    except Exception:
        log.exception("Error processing Telegram webhook update.")
    return "ok", 200

init_db()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
