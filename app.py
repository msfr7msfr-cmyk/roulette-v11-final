import os
import re
import json
import time
import hmac
import math
import sqlite3
import logging
from collections import Counter, defaultdict
from typing import List, Tuple, Dict, Optional

import requests
from flask import Flask, request, abort

TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DB_FILE = os.getenv("DATABASE_PATH", "roulette.sqlite3")
MIN_HISTORY = 100
MAX_HISTORY = 2000
LOOKBACK_DEFAULT = 180

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("roulette_v25_smart")
HTTP = requests.Session()

WHEEL = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36,
    11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9,
    22, 18, 29, 7, 28, 12, 35, 3, 26
]
WHEEL_INDEX = {n: i for i, n in enumerate(WHEEL)}
WHEEL_SIZE = 37

RED = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
BLACK = set(range(1, 37)) - RED

def wheel_dist(a: int, b: int) -> int:
    d = abs(WHEEL_INDEX[a] - WHEEL_INDEX[b]) % WHEEL_SIZE
    return min(d, WHEEL_SIZE - d)

def wheel_step(a: int, b: int) -> int:
    d = (WHEEL_INDEX[b] - WHEEL_INDEX[a]) % WHEEL_SIZE
    if d > WHEEL_SIZE // 2:
        d -= WHEEL_SIZE
    return int(d)

def neighbors(c: int, r: int = 2) -> List[int]:
    idx = WHEEL_INDEX[c]
    return [WHEEL[(idx + offset) % WHEEL_SIZE] for offset in range(-r, r + 1)]

def decay_weights(n: int, halflife: float = 40.0) -> List[float]:
    return [0.5 ** ((n - 1 - i) / halflife) for i in range(n)]

def chi_square_bias(history: List[int], lookback: int = 200) -> float:
    recent = history[-lookback:]
    if len(recent) < 50:
        return 0.0
    counts = Counter(recent)
    expected = len(recent) / 37.0
    chi2 = sum((counts.get(i, 0) - expected) ** 2 / expected for i in range(37))
    return chi2

def score_frequency(history: List[int], lookback: int = 150, halflife: float = 32.0) -> List[float]:
    recent = history[-lookback:]
    weights = decay_weights(len(recent), halflife)
    scores = [0.0] * 37
    for number, weight in zip(recent, weights):
        scores[number] += weight
    total = sum(scores) or 1.0
    return [s / total for s in scores]

def score_neighbor_affinity(history: List[int], lookback: int = 120) -> Tuple[List[float], List[float]]:
    recent = history[-lookback:]
    if len(recent) < 12:
        return [0.0] * 37, [0.0] * 37
    near1 = [0.0] * 37
    near2 = [0.0] * 37
    weights = decay_weights(len(recent), 28.0)
    for i, number in enumerate(recent):
        w = weights[i]
        for candidate in range(37):
            d = wheel_dist(candidate, number)
            if d == 0:
                continue
            if d <= 1:
                near1[candidate] += w
            if d <= 2:
                near2[candidate] += w
    t1 = sum(near1) or 1.0
    t2 = sum(near2) or 1.0
    return [x / t1 for x in near1], [x / t2 for x in near2]

def score_step_distribution(history: List[int], lookback: int = 140) -> List[float]:
    if len(history) < 25:
        return [1.0 / 37] * 37
    segment = history[-lookback:]
    steps = [wheel_step(segment[i - 1], segment[i]) for i in range(1, len(segment))]
    step_counts = Counter(steps)
    total = sum(step_counts.values()) or 1
    last = history[-1]
    scores = [0.0] * 37
    for candidate in range(37):
        step = wheel_step(last, candidate)
        scores[candidate] = (step_counts.get(step, 0) + 0.4) / (total + 0.4 * 37)
    total_score = sum(scores) or 1.0
    return [s / total_score for s in scores]

def score_direction(history: List[int], lookback: int = 50) -> Tuple[float, float]:
    if len(history) < 8:
        return 0.5, 0.5
    segment = history[-lookback:]
    steps = [wheel_step(segment[i - 1], segment[i]) for i in range(1, len(segment))]
    steps = [s for s in steps if s!= 0]
    if not steps:
        return 0.5, 0.5
    cw = sum(1 for s in steps if s > 0)
    return cw / len(steps), 1.0 - (cw / len(steps))

def score_markov(history: List[int], lookback: int = 250, order: int = 1) -> List[float]:
    if len(history) < 40:
        return [1.0 / 37] * 37
    segment = history[-lookback:]
    if order == 1:
        transitions = defaultdict(Counter)
        for i in range(1, len(segment)):
            prev = WHEEL_INDEX[segment[i - 1]]
            curr = WHEEL_INDEX[segment[i]]
            transitions[prev][curr] += 1
        last_pos = WHEEL_INDEX[history[-1]]
        row = transitions.get(last_pos, Counter())
        total = sum(row.values())
        scores = [(row.get(p, 0) + 0.6) / (total + 0.6 * 37) for p in range(37)]
    else:
        transitions = defaultdict(Counter)
        for i in range(2, len(segment)):
            key = (WHEEL_INDEX[segment[i - 2]], WHEEL_INDEX[segment[i - 1]])
            curr = WHEEL_INDEX[segment[i]]
            transitions[key][curr] += 1
        if len(history) < 3:
            return [1.0 / 37] * 37
        key = (WHEEL_INDEX[history[-2]], WHEEL_INDEX[history[-1]])
        row = transitions.get(key, Counter())
        total = sum(row.values())
        scores = [(row.get(p, 0) + 0.7) / (total + 0.7 * 37) for p in range(37)]
    total_score = sum(scores) or 1.0
    return [s / total_score for s in scores]

def score_hot_arcs(history: List[int], lookback: int = 80, arc_radius: int = 3) -> List[float]:
    recent = history[-lookback:]
    if not recent:
        return [1.0 / 37] * 37
    weights = decay_weights(len(recent), 22.0)
    activity = [0.0] * 37
    for number, w in zip(recent, weights):
        for cand in neighbors(number, arc_radius):
            activity[cand] += w
    total = sum(activity) or 1.0
    return [v / total for v in activity]

def score_color_parity_trend(history: List[int], lookback: int = 30) -> List[float]:
    recent = history[-lookback:]
    if len(recent) < 10:
        return [1.0 / 37] * 37
    red_cnt = sum(1 for n in recent if n in RED)
    black_cnt = sum(1 for n in recent if n in BLACK)
    odd_cnt = sum(1 for n in recent if n % 2 == 1 and n!= 0)
    even_cnt = sum(1 for n in recent if n % 2 == 0 and n!= 0)
    prefer_red = red_cnt > black_cnt + 3
    prefer_black = black_cnt > red_cnt + 3
    prefer_odd = odd_cnt > even_cnt + 3
    prefer_even = even_cnt > odd_cnt + 3
    scores = [1.0] * 37
    for i in range(37):
        if prefer_red and i in RED:
            scores[i] *= 1.12
        if prefer_black and i in BLACK:
            scores[i] *= 1.12
        if prefer_odd and i % 2 == 1 and i!= 0:
            scores[i] *= 1.08
        if prefer_even and i % 2 == 0 and i!= 0:
            scores[i] *= 1.08
    total = sum(scores) or 1.0
    return [s / total for s in scores]

def combine_scores(history: List[int], adaptive_boost: float = 1.0) -> List[float]:
    if not history:
        return [1.0 / 37] * 37
    hist = history[-MAX_HISTORY:]
    freq = score_frequency(hist)
    near1, near2 = score_neighbor_affinity(hist)
    steps = score_step_distribution(hist)
    p_cw, p_ccw = score_direction(hist)
    markov1 = score_markov(hist, order=1)
    markov2 = score_markov(hist, order=2)
    hot = score_hot_arcs(hist)
    color_par = score_color_parity_trend(hist)
    bias = chi_square_bias(hist)
    bias_factor = min(1.35, 1.0 + (bias - 40) / 120) if bias > 45 else 1.0
    base_w = {
        "freq": 0.13 * adaptive_boost,
        "near1": 0.12,
        "near2": 0.09,
        "step": 0.16,
        "markov1": 0.15,
        "markov2": 0.11,
        "hot": 0.14 * bias_factor,
        "color": 0.05,
        "dir": 0.05
    }
    total_w = sum(base_w.values())
    w = {k: v / total_w for k, v in base_w.items()}
    scores = [0.0] * 37
    last = hist[-1]
    for i in range(37):
        scores[i] = (
            w["freq"] * freq[i]
            + w["near1"] * near1[i]
            + w["near2"] * near2[i]
            + w["step"] * steps[i]
            + w["markov1"] * markov1[i]
            + w["markov2"] * markov2[i]
            + w["hot"] * hot[i]
            + w["color"] * color_par[i]
        )
        dist = wheel_step(last, i)
        if dist > 0:
            scores[i] += w["dir"] * p_cw / (1.0 + abs(dist) * 0.7)
        elif dist < 0:
            scores[i] += w["dir"] * p_ccw / (1.0 + abs(dist) * 0.7)
    total = sum(scores) or 1.0
    return [s / total for s in scores]

def select_top20_smart(scores: List[float], diversity: float = 0.65) -> List[int]:
    ranked = sorted(range(37), key=lambda n: scores[n], reverse=True)
    chosen = []
    used = set()
    for cand in ranked:
        if len(chosen) >= 20:
            break
        if cand in used:
            continue
        close_count = sum(1 for n in chosen if wheel_dist(n, cand) <= 1)
        if close_count >= 3 and diversity > 0.5:
            continue
        chosen.append(cand)
        used.add(cand)
    for cand in ranked:
        if len(chosen) >= 20:
            break
        if cand not in used:
            chosen.append(cand)
            used.add(cand)
    return chosen

def find_best_arcs(top_numbers: List[int], scores: List[float], num_arcs: int = 4, arc_size: int = 5) -> List[List[int]]:
    if not top_numbers:
        return [[] for _ in range(num_arcs)]
    candidates = sorted(top_numbers, key=lambda n: scores[n], reverse=True)
    used = set()
    arcs = []
    for center in candidates:
        if len(arcs) >= num_arcs:
            break
        if center in used:
            continue
        arc = []
        for offset in range(-2, 3):
            idx = (WHEEL_INDEX[center] + offset) % WHEEL_SIZE
            num = WHEEL[idx]
            if num in top_numbers and num not in used:
                arc.append(num)
        if len(arc) < arc_size:
            for n in candidates:
                if n not in used and n not in arc:
                    arc.append(n)
                if len(arc) >= arc_size:
                    break
        arc = arc[:arc_size]
        if len(arc) >= 3:
            arcs.append(arc)
            used.update(arc)
    while len(arcs) < num_arcs:
        remaining = [n for n in candidates if n not in used]
        if not remaining:
            break
        cluster = remaining[:arc_size]
        arcs.append(cluster)
        used.update(cluster)
    return arcs[:num_arcs]

def calculate_v25(history: List[int], recent_hit_rate: float = 0.54) -> Tuple[List[int], List[int], List[int], List[int], List[int]]:
    if any(not isinstance(n, int) or not 0 <= n <= 36 for n in history):
        raise ValueError("يجب أن تكون الأرقام أعدادًا صحيحة بين 0 و36")
    if not history:
        base = WHEEL[:20]
        return base[:5], base[5:10], base[10:15], base[15:20], base
    adaptive = 1.0 + max(-0.15, min(0.25, (recent_hit_rate - 0.54) * 1.8))
    scores = combine_scores(history, adaptive_boost=adaptive)
    top20 = select_top20_smart(scores)
    arcs = find_best_arcs(top20, scores, num_arcs=4, arc_size=5)
    s1 = arcs[0] if len(arcs) > 0 else top20[:5]
    s2 = arcs[1] if len(arcs) > 1 else top20[5:10]
    s3 = arcs[2] if len(arcs) > 2 else top20[10:15]
    s4 = arcs[3] if len(arcs) > 3 else top20[15:20]
    final = []
    seen = set()
    for group in (s1, s2, s3, s4):
        for n in group:
            if n not in seen:
                final.append(n)
                seen.add(n)
    for n in top20:
        if len(final) >= 20:
            break
        if n not in seen:
            final.append(n)
            seen.add(n)
    return s1, s2, s3, s4, final[:20]

def backtest_accuracy(history: List[int], top_n: int = 20, test_len: int = 120) -> Optional[float]:
    if len(history) < test_len + MIN_HISTORY:
        return None
    hits = 0
    start = len(history) - test_len
    for t in range(start, len(history)):
        training = history[:t]
        scores = combine_scores(training)
        top = set(sorted(range(37), key=lambda n: scores[n], reverse=True)[:top_n])
        hits += int(history[t] in top)
    return hits / test_len

def connect_db():
    con = sqlite3.connect(DB_FILE, timeout=30)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with connect_db() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id TEXT PRIMARY KEY,
            history TEXT NOT NULL DEFAULT '[]',
            sec1 TEXT NOT NULL DEFAULT '[]',
            sec2 TEXT NOT NULL DEFAULT '[]',
            sec3 TEXT NOT NULL DEFAULT '[]',
            sec4 TEXT NOT NULL DEFAULT '[]',
            prediction TEXT NOT NULL DEFAULT '[]',
            hits INTEGER NOT NULL DEFAULT 0,
            misses INTEGER NOT NULL DEFAULT 0,
            total_bet INTEGER NOT NULL DEFAULT 0,
            recent_hits INTEGER NOT NULL DEFAULT 0,
            recent_total INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS updates_seen (
            update_id TEXT PRIMARY KEY
        );
        """)
        cols = {row[1] for row in con.execute("PRAGMA table_info(users)").fetchall()}
        if "recent_hits" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN recent_hits INTEGER NOT NULL DEFAULT 0")
        if "recent_total" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN recent_total INTEGER NOT NULL DEFAULT 0")

init_db()

def get_user(chat_id: str) -> dict:
    with connect_db() as con:
        row = con.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        if row is None:
            con.execute("INSERT INTO users(chat_id) VALUES(?)", (str(chat_id),))
            row = con.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        return dict(row)

def save_user(chat_id: str, **values):
    allowed = {
        "history", "sec1", "sec2", "sec3", "sec4", "prediction",
        "hits", "misses", "total_bet", "recent_hits", "recent_total"
    }
    fields, params = [], []
    for key, value in values.items():
        if key not in allowed:
            continue
        if key in {"history", "sec1", "sec2", "sec3", "sec4", "prediction"}:
            value = json.dumps(value)
        fields.append(f"{key}=?")
        params.append(value)
    if not fields:
        return
    params.append(str(chat_id))
    with connect_db() as con:
        con.execute(f"UPDATE users SET {', '.join(fields)} WHERE chat_id=?", params)

def reset_user(chat_id: str):
    with connect_db() as con:
        con.execute("""
        INSERT INTO users (chat_id, history, sec1, sec2, sec3, sec4, prediction,
                           hits, misses, total_bet, recent_hits, recent_total)
        VALUES (?, '[]', '[]', '[]', '[]', '[]', '[]', 0, 0, 0, 0, 0)
        ON CONFLICT(chat_id) DO UPDATE SET
            history='[]', sec1='[]', sec2='[]', sec3='[]', sec4='[]',
            prediction='[]', hits=0, misses=0, total_bet=0,
            recent_hits=0, recent_total=0
        """, (str(chat_id),))

def send_message(chat_id, text: str) -> bool:
    if not TOKEN:
        log.error("BOT_TOKEN غير مضبوط")
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r = HTTP.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
            "parse_mode": "HTML"
        }, timeout=15)
        if not r.ok:
            log.error("Telegram API error: %s", r.text)
            HTTP.post(url, json={"chat_id": chat_id, "text": text}, timeout=15)
            return False
        return True
    except requests.RequestException:
        log.exception("تعذر إرسال الرسالة")
        return False

def parse_numbers(text: str) -> List[int]:
    tokens = [t for t in re.split(r"[\s,;،\n]+", text.strip()) if t]
    numbers = []
    for token in tokens:
        if not re.fullmatch(r"\d+", token):
            raise ValueError(f"صيغة رقم غير صحيحة: {token}")
        number = int(token)
        if not 0 <= number <= 36:
            raise ValueError(f"الرقم {number} خارج النطاق 0-36")
        numbers.append(number)
    return numbers

def record_spin(chat_id: str, update_id: str, number: int) -> Optional[dict]:
    with connect_db() as con:
        try:
            con.execute("INSERT INTO updates_seen(update_id) VALUES(?)", (str(update_id),))
        except sqlite3.IntegrityError:
            return None
        row = con.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        if row is None:
            return None
        user = dict(row)
        history = json.loads(user["history"])
        prediction = json.loads(user["prediction"])
        if len(history) < MIN_HISTORY:
            return None
        hit = number in prediction if prediction else False
        hits = user["hits"] + int(hit)
        misses = user["misses"] + int(not hit)
        recent_hits = user.get("recent_hits", 0) + int(hit)
        recent_total = user.get("recent_total", 0) + 1
        if recent_total > 40:
            recent_hits = int(recent_hits * 0.85)
            recent_total = int(recent_total * 0.85)
        history.append(number)
        if len(history) > MAX_HISTORY:
            history = history[-MAX_HISTORY:]
        recent_rate = recent_hits / recent_total if recent_total > 5 else 0.54
        s1, s2, s3, s4, new_pred = calculate_v25(history, recent_hit_rate=recent_rate)
        con.execute("""
        UPDATE users SET
            history=?, sec1=?, sec2=?, sec3=?, sec4=?, prediction=?,
            hits=?, misses=?, recent_hits=?, recent_total=?
        WHERE chat_id=?
        """, (
            json.dumps(history), json.dumps(s1), json.dumps(s2),
            json.dumps(s3), json.dumps(s4), json.dumps(new_pred),
            hits, misses, recent_hits, recent_total, str(chat_id)
        ))
        return {
            "hit": hit,
            "number": number,
            "new_s1": s1, "new_s2": s2, "new_s3": s3, "new_s4": s4,
            "new_pred": new_pred,
            "hits": hits, "misses": misses,
            "recent_rate": recent_rate
        }

def help_message() -> str:
    return (
        "🎯 <b>بوت الروليت V25 – محرك إحصائي متقدم</b>\n\n"
        "🧠 التحسينات:\n"
        "• تكرار مرجح + جوار فيزيائي\n"
        "• ماركوف درجة 1 و 2\n"
        "• أقواس ساخنة على العجلة\n"
        "• كشف انحياز (chi²)\n"
        "• أوزان تكيفية حسب الأداء الحديث\n"
        "• اتجاه + لون/زوجي ثانوي\n\n"
        "1. أرسل ≥100 رقم لتفعيل النموذج.\n"
        "2. يمكنك الإرسال على دفعات.\n"
        "3. بعد التفعيل أرسل كل نتيجة جديدة منفردة.\n\n"
        "/start – إعادة ضبط\n"
        "/status – الأهداف الحالية\n"
        "/stats – إحصاءات الأداء\n"
        "/backtest – اختبار تاريخي\n"
        "/help – المساعدة\n\n"
        "⚠️ <b>تحذير مهم:</b> لا توجد خوارزمية تضمن الرقم القادم. "
        "الروليت عشوائي وهامش الكازينو موجود دائمًا. استخدمه للتحليل فقط."
    )

def process_message(message: dict, update_id: str):
    chat_id = str(message["chat"]["id"])
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
        sectors = [json.loads(user.get(f"sec{i}", "[]")) for i in range(1, 5)]
        last = history[-1] if history else "لا يوجد"
        send_message(chat_id,
            f"📊 <b>الأهداف الحالية V25</b>\n"
            f"آخر رقم: <b>{last}</b>\n"
            f"حجم السجل: <b>{len(history)}</b>\n\n"
            f"🔵 القطاع 1: <code>{sectors[0]}</code>\n"
            f"🟢 القطاع 2: <code>{sectors[1]}</code>\n"
            f"🟡 القطاع 3: <code>{sectors[2]}</code>\n"
            f"🟣 القطاع 4: <code>{sectors[3]}</code>"
        )
        return
    if text == "/stats":
        hits = user["hits"]
        misses = user["misses"]
        total = hits + misses
        rate = hits / total * 100 if total else 0.0
        baseline = 20 / 37 * 100
        expected = total * 20 / 37
        recent_rate = (user.get("recent_hits", 0) / user.get("recent_total", 1) * 100) if user.get("recent_total", 0) > 0 else 0
        send_message(chat_id,
            "📈 <b>تقرير الأداء V25</b>\n\n"
            f"إجمالي اللفات المسجلة: <b>{total}</b>\n"
            f"الإصابات: <b>{hits}</b>\n"
            f"الإخفاقات: <b>{misses}</b>\n"
            f"التغطية الفعلية: <b>{rate:.1f}%</b>\n"
            f"التغطية الحديثة: <b>{recent_rate:.1f}%</b>\n"
            f"خط الأساس العشوائي: <b>{baseline:.1f}%</b>\n"
            f"الإصابات المتوقعة عشوائيًا: <b>{expected:.1f}</b>\n"
            f"الفرق: <b>{rate - baseline:+.1f}</b> نقطة\n\n"
            "⚠️ الأداء السابق لا يضمن المستقبل."
        )
        return
    if text == "/backtest":
        if len(history) < MIN_HISTORY + 40:
            send_message(chat_id, f"تحتاج إلى {MIN_HISTORY + 40} رقمًا على الأقل للاختبار.")
            return
        test_len = min(150, len(history) - MIN_HISTORY)
        accuracy = backtest_accuracy(history, top_n=20, test_len=test_len)
        if accuracy is None:
            send_message(chat_id, "السجل غير كافٍ.")
            return
        baseline = 20 / 37
        send_message(chat_id,
            f"🧪 <b>الاختبار التاريخي V25</b>\n"
            f"عدد اللفات المختبرة: <b>{test_len}</b>\n"
            f"تغطية النموذج: <b>{accuracy * 100:.1f}%</b>\n"
            f"خط الأساس: <b>{baseline * 100:.1f}%</b>\n"
            f"الفرق: <b>{(accuracy - baseline) * 100:+.1f}</b> نقطة\n\n"
            "هذا اختبار على الماضي فقط."
        )
        return
    try:
        numbers = parse_numbers(text)
    except ValueError as e:
        send_message(chat_id, f"⚠️ {e}")
        return
    if not numbers:
        return
    if len(numbers) >= MIN_HISTORY:
        s1, s2, s3, s4, prediction = calculate_v25(numbers)
        save_user(chat_id, history=numbers, sec1=s1, sec2=s2, sec3=s3, sec4=s4,
                  prediction=prediction, hits=0, misses=0, recent_hits=0, recent_total=0)
        send_message(chat_id,
            "✅ <b>تم تفعيل V25</b>\n"
            f"حجم السجل: <b>{len(numbers)}</b>\n"
            f"آخر رقم: <b>{numbers[-1]}</b>\n\n"
            f"🔵 <code>{s1}</code>\n"
            f"🟢 <code>{s2}</code>\n"
            f"🟡 <code>{s3}</code>\n"
            f"🟣 <code>{s4}</code>"
        )
        return
    if len(history) < MIN_HISTORY:
        combined = history + numbers
        if len(combined) < MIN_HISTORY:
            save_user(chat_id, history=combined)
            send_message(chat_id,
                f"📥 تم حفظ {len(numbers)} رقمًا.\n"
                f"المجموع: <b>{len(combined)}/{MIN_HISTORY}</b>\n"
                "أكمل الأرقام."
            )
            return
        s1, s2, s3, s4, prediction = calculate_v25(combined)
        save_user(chat_id, history=combined, sec1=s1, sec2=s2, sec3=s3, sec4=s4,
                  prediction=prediction, hits=0, misses=0, recent_hits=0, recent_total=0)
        send_message(chat_id,
            "✅ <b>اكتمل السجل وتفعّل النموذج</b>\n"
            f"عدد الأرقام: <b>{len(combined)}</b>\n"
            f"آخر رقم: <b>{combined[-1]}</b>\n\n"
            f"🔵 <code>{s1}</code>\n"
            f"🟢 <code>{s2}</code>\n"
            f"🟡 <code>{s3}</code>\n"
            f"🟣 <code>{s4}</code>"
        )
        return
    if len(numbers)!= 1:
        send_message(chat_id, "بعد التفعيل أرسل كل نتيجة جديدة منفردة (رقم واحد).")
        return
    result = record_spin(chat_id, update_id, numbers[0])
    if result is None:
        send_message(chat_id, "⚠️ تعذر تسجيل اللفة (ربما مكررة أو خطأ داخلي).")
        return
    icon = "🟢 <b>إصابة 🎯</b>" if result["hit"] else "🔴 <b>إخفاق</b>"
    send_message(chat_id,
        f"{icon}: <b>{result['number']}</b>\n\n"
        f"الإصابات: <b>{result['hits']}</b> | الإخفاقات: <b>{result['misses']}</b>\n"
        f"معدل حديث تقريبي: <b>{result['recent_rate']*100:.1f}%</b>\n\n"
        "🎯 <b>الأهداف الجديدة</b>\n"
        f"🔵 <code>{result['new_s1']}</code>\n"
        f"🟢 <code>{result['new_s2']}</code>\n"
        f"🟡 <code>{result['new_s3']}</code>\n"
        f"🟣 <code>{result['new_s4']}</code>"
    )

@app.get("/")
def home():
    return "Roulette V25 Smart Statistical Engine is running.", 200

@app.post("/telegram-webhook")
def webhook():
    if WEBHOOK_SECRET:
        supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(supplied, WEBHOOK_SECRET):
            abort(403)
    update = request.get_json(silent=True)
    if not isinstance(update, dict):
        return "ok", 200
    message = update.get("message")
    if not isinstance(message, dict):
        return "ok", 200
    try:
        process_message(message, str(update.get("update_id", time.time_ns())))
    except Exception:
        log.exception("حدث خطأ أثناء معالجة تحديث تيليجرام")
    return "ok", 200

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
