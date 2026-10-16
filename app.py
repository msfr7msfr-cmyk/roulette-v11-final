# -*- coding: utf-8 -*-
"""
بوت الروليت V24 — تحليل إحصائي صادق (بدون ادعاءات تنبؤ)
حقيقة رياضية: لفات عجلة الروليت الأوروبية (37 رقماً) أحداث مستقلة ومتساوية
الاحتمال. لا توجد خوارزمية تعرف الرقم القادم.
"""
import os
import re
import json
import time
import hmac
import sqlite3
import logging
import math
from collections import Counter, defaultdict
from flask import Flask, request, abort
import requests

TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DB_FILE = os.getenv("DATABASE_PATH", "roulette.sqlite3")
MIN_HISTORY = 100
MIN_SPINS_BIAS = 1000
COVER_N = 20
N_NUMBERS = 37
MAX_BACKTEST_TRAIN = 15000

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("roulette_v24")
HTTP = requests.Session()

WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23,
         10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]
WHEEL_INDEX = {n: i for i, n in enumerate(WHEEL)}
WHEEL_SIZE = len(WHEEL)
assert WHEEL_SIZE == N_NUMBERS and sorted(WHEEL) == list(range(N_NUMBERS))

def wheel_dist(a, b):
    d = abs(WHEEL_INDEX[a] - WHEEL_INDEX[b]) % WHEEL_SIZE
    return min(d, WHEEL_SIZE - d)

def wheel_step(a, b):
    d = (WHEEL_INDEX[b] - WHEEL_INDEX[a]) % WHEEL_SIZE
    if d > WHEEL_SIZE / 2:
        d -= WHEEL_SIZE
    return int(d)

def neighbors(c, r=2):
    idx = WHEEL_INDEX[c]
    return [WHEEL[(idx + o) % WHEEL_SIZE] for o in range(-r, r + 1)]

def _normalize(vec):
    t = sum(vec)
    if t <= 0:
        return [1.0 / N_NUMBERS] * N_NUMBERS
    return [v / t for v in vec]

def _decay_weights(n, halflife=40.0):
    return [0.5 ** ((n - 1 - i) / halflife) for i in range(n)]

def _gammaincc(a, x):
    if a <= 0 or x < 0:
        raise ValueError("bad args")
    if x == 0:
        return 1.0
    if x < a + 1.0:
        ap, summ, delta = a, 1.0 / a, 1.0 / a
        for _ in range(1000):
            ap += 1.0
            delta *= x / ap
            summ += delta
            if abs(delta) < abs(summ) * 1e-15:
                break
        return 1.0 - summ * math.exp(-x + a * math.log(x) - math.lgamma(a))
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < 1e-15:
            break
    return h * math.exp(-x + a * math.log(x) - math.lgamma(a))

def chi_square_uniform(counts):
    n = sum(counts)
    k = len(counts)
    if n <= 0:
        return 0.0, k - 1, 1.0
    e = n / float(k)
    chi2 = sum((c - e) ** 2 / e for c in counts)
    df = k - 1
    return chi2, df, _gammaincc(df / 2.0, chi2 / 2.0)

def chi2_critical(df, alpha=0.05):
    lo, hi = 0.0, 1000.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if _gammaincc(df / 2.0, mid / 2.0) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0

def binomial_two_sided_p(hits, n, p):
    if n <= 0:
        return 1.0
    if p <= 0.0 or p >= 1.0:
        return 1.0 if hits == round(n * p) else 0.0
    if n <= 1000:
        lg = math.lgamma
        def pmf(k):
            return math.exp(lg(n + 1) - lg(k + 1) - lg(n - k + 1)
                            + k * math.log(p) + (n - k) * math.log1p(-p))
        obs = pmf(hits)
        total = 0.0
        for k in range(n + 1):
            pk = pmf(k)
            if pk <= obs * (1.0 + 1e-9):
                total += pk
        return min(1.0, total)
    sd = math.sqrt(n * p * (1 - p))
    if sd <= 0:
        return 1.0
    z = (abs(hits - n * p) - 0.5) / sd
    return math.erfc(max(z, 0.0) / math.sqrt(2.0))

def _score_prior():
    return [1.0 / N_NUMBERS] * N_NUMBERS

def _score_frequency(history, lookback=150, halflife=30.0):
    recent = history[-lookback:]
    w = _decay_weights(len(recent), halflife)
    score = [0.0] * N_NUMBERS
    for num, weight in zip(recent, w):
        score[num] += weight
    return _normalize(score)

def _score_neighbor_affinity(history, lookback=120):
    recent = history[-lookback:]
    if len(recent) < 10:
        return _score_prior(), _score_prior()
    near1 = [0.0] * N_NUMBERS
    near2 = [0.0] * N_NUMBERS
    w = _decay_weights(len(recent), 25.0)
    for i, num in enumerate(recent):
        for cand in range(N_NUMBERS):
            d = wheel_dist(cand, num)
            if d == 0:
                continue
            if d <= 1:
                near1[cand] += w[i]
            if d <= 2:
                near2[cand] += w[i]
    return _normalize(near1), _normalize(near2)

def _score_step_distribution(history, lookback=120):
    if len(history) < 20:
        return _score_prior()
    seg = history[-lookback:]
    steps = [wheel_step(seg[i - 1], seg[i]) for i in range(1, len(seg))]
    counter = Counter(steps)
    total = sum(counter.values())
    last = history[-1]
    alpha = 0.5
    score = [0.0] * N_NUMBERS
    for cand in range(N_NUMBERS):
        s = wheel_step(last, cand)
        score[cand] = (counter.get(s, 0) + alpha) / (total + alpha * N_NUMBERS)
    return _normalize(score)

def _score_direction(history, lookback=50):
    if len(history) < 5:
        return 0.5, 0.5
    seg = history[-lookback:]
    steps = [wheel_step(seg[i - 1], seg[i]) for i in range(1, len(seg))]
    steps = [s for s in steps if s!= 0]
    if not steps:
        return 0.5, 0.5
    cw = sum(1 for s in steps if s > 0)
    return cw / float(len(steps)), (len(steps) - cw) / float(len(steps))

def _score_markov(history, lookback=250, min_support=3):
    if len(history) < 40:
        return _score_prior()
    seg = history[-lookback:]
    trans1 = defaultdict(Counter)
    trans2 = defaultdict(Counter)
    for i in range(1, len(seg)):
        a, b = seg[i - 1], seg[i]
        trans1[a][b] += 1
        if i >= 2:
            trans2[(seg[i - 2], a)][b] += 1
    last = seg[-1]
    prev = seg[-2] if len(seg) >= 2 else last
    row = trans2.get((prev, last))
    if not row or sum(row.values()) < min_support:
        row = trans1.get(last, Counter())
    alpha = 1.0
    return _normalize([row.get(n, 0) + alpha for n in range(N_NUMBERS)])

def _score_hot_sectors(history, lookback=60, radius=2):
    recent = history[-lookback:]
    if not recent:
        return _score_prior()
    w = _decay_weights(len(recent), 20.0)
    activity = [0.0] * N_NUMBERS
    for num, weight in zip(recent, w):
        for cand in neighbors(num, radius):
            activity[cand] += weight
    return _normalize(activity)

BASE_WEIGHTS = {"freq": 0.18, "near1": 0.14, "near2": 0.10, "step": 0.20,
                "markov": 0.22, "hot": 0.11, "dir": 0.05}

def _combine_scores(history):
    if not history:
        return _score_prior()
    W = dict(BASE_WEIGHTS)
    f = _score_frequency(history)
    n1, n2 = _score_neighbor_affinity(history)
    st = _score_step_distribution(history)
    mk = _score_markov(history)
    ho = _score_hot_sectors(history)
    p_cw, p_ccw = _score_direction(history)
    last = history[-1]
    raw = [0.0] * N_NUMBERS
    for n in range(N_NUMBERS):
        raw[n] = (W["freq"] * f[n] + W["near1"] * n1[n] + W["near2"] * n2[n]
                  + W["step"] * st[n] + W["markov"] * mk[n] + W["hot"] * ho[n])
        d = wheel_step(last, n)
        if d > 0:
            raw[n] += W["dir"] * p_cw / (1.0 + abs(d))
        elif d < 0:
            raw[n] += W["dir"] * p_ccw / (1.0 + abs(d))
    return _normalize(raw)

def _top_cover(scores, k=COVER_N):
    return sorted(range(N_NUMBERS), key=lambda n: scores[n], reverse=True)[:k]

def _best_windows(scores, n_windows=4, window=5):
    used = set()
    windows = []
    for _ in range(n_windows):
        best, best_val = None, None
        for start in range(WHEEL_SIZE):
            nums = [WHEEL[(start + o) % WHEEL_SIZE] for o in range(window)]
            if any(x in used for x in nums):
                continue
            val = sum(scores[n] for n in nums)
            if best_val is None or val > best_val:
                best_val, best = val, nums
        if best is None:
            rem = sorted((n for n in range(N_NUMBERS) if n not in used),
                         key=lambda n: scores[n], reverse=True)[:window]
            best = rem
        if not best:
            break
        used.update(best)
        windows.append(best)
    while len(windows) < n_windows:
        windows.append([])
    return windows

def calculate_sectors(history):
    scores = _combine_scores(history)
    windows = _best_windows(scores)
    union, seen = [], set()
    for w in windows:
        for n in w:
            if n not in seen:
                seen.add(n)
                union.append(n)
    for n in sorted(range(N_NUMBERS), key=lambda x: scores[x], reverse=True):
        if len(union) >= COVER_N:
            break
        if n not in seen:
            seen.add(n)
            union.append(n)
    return windows[0], windows[1], windows[2], windows[3], union[:COVER_N], scores

def wilson_ci(hits, n, z=1.96):
    if n <= 0:
        return (0.0, 0.0)
    p = hits / float(n)
    d = 1.0 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    lo = (c - h) / d
    hi = (c + h) / d
    return (max(0.0, lo), min(1.0, hi))

def bias_test(history, min_spins=MIN_SPINS_BIAS):
    n = len(history)
    if n < min_spins:
        return None
    counts = [0] * N_NUMBERS
    for x in history:
        counts[x] += 1
    chi2, df, p = chi_square_uniform(counts)
    crit = chi2_critical(df, 0.05)
    exp = n / float(N_NUMBERS)
    best_win, best_cnt = None, None
    for start in range(WHEEL_SIZE):
        nums = [WHEEL[(start + o) % WHEEL_SIZE] for o in range(5)]
        c = sum(counts[x] for x in nums)
        if best_cnt is None or c > best_cnt:
            best_cnt, best_win = c, nums
    p_win = 5.0 / N_NUMBERS
    sd_win = math.sqrt(n * p_win * (1 - p_win))
    z_win = (best_cnt - n * p_win) / sd_win if sd_win > 0 else 0.0
    return {
        "n": n, "chi2": chi2, "df": df, "p_value": p, "critical": crit,
        "expected": exp,
        "most": max(range(N_NUMBERS), key=lambda x: counts[x]),
        "most_count": max(counts),
        "least": min(range(N_NUMBERS), key=lambda x: counts[x]),
        "least_count": min(counts),
        "hot_window": best_win, "hot_window_count": best_cnt, "hot_window_z": z_win,
        "significant": p < 0.05,
    }

def walk_forward_backtest(history, cover_n=COVER_N, test_len=200):
    n = len(history)
    if n < MIN_HISTORY + 20:
        return None
    start = max(MIN_HISTORY, n - test_len)
    hits, total = 0, 0
    for t in range(start, n):
        sub = history[:t]
        if len(sub) > MAX_BACKTEST_TRAIN:
            sub = sub[-MAX_BACKTEST_TRAIN:]
        cover = set(_top_cover(_combine_scores(sub), cover_n))
        total += 1
        if history[t] in cover:
            hits += 1
    if total == 0:
        return None
    p0 = cover_n / float(N_NUMBERS)
    lo, hi = wilson_ci(hits, total)
    return {"hits": hits, "total": total, "acc": hits / float(total),
            "expected": p0, "p_value": binomial_two_sided_p(hits, total, p0),
            "ci_low": lo, "ci_high": hi}

from contextlib import contextmanager
@contextmanager
def db():
    con = sqlite3.connect(DB_FILE, timeout=20)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()

SCHEMA = """
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
    total_bet INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS updates_seen (update_id TEXT PRIMARY KEY);
"""

def init_db():
    with db() as con:
        con.execute("PRAGMA journal_mode=WAL;")
        con.executescript(SCHEMA)

def get_user(chat_id):
    with db() as con:
        row = con.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        if row is None:
            con.execute("INSERT INTO users(chat_id) VALUES(?)", (str(chat_id),))
            con.commit()
            row = con.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        return dict(row)

def save_user(chat_id, **vals):
    allowed = {"history", "sec1", "sec2", "sec3", "sec4", "prediction",
               "hits", "misses", "total_bet"}
    fields, params = [], []
    for k, v in vals.items():
        if k not in allowed:
            continue
        if k in ("history", "sec1", "sec2", "sec3", "sec4", "prediction"):
            v = json.dumps(v)
        fields.append(k + "=?")
        params.append(v)
    if not fields:
        return
    params.append(str(chat_id))
    with db() as con:
        con.execute("UPDATE users SET " + ", ".join(fields) + " WHERE chat_id=?", params)

def reset_user(chat_id):
    with db() as con:
        con.execute("INSERT INTO users(chat_id) VALUES(?) ON CONFLICT(chat_id) DO UPDATE SET "
                    "history='[]',sec1='[]',sec2='[]',sec3='[]',sec4='[]',"
                    "prediction='[]',hits=0,misses=0,total_bet=0", (str(chat_id),))

def _seen_update(update_id):
    with db() as con:
        return con.execute("SELECT 1 FROM updates_seen WHERE update_id=?",
                           (str(update_id),)).fetchone() is not None

def _mark_update(update_id):
    with db() as con:
        try:
            con.execute("INSERT INTO updates_seen(update_id) VALUES(?)", (str(update_id),))
            con.commit()
            return True
        except sqlite3.IntegrityError:
            return False

def send_message(chat_id, text):
    if not TOKEN:
        return False
    url = "https://api.telegram.org/bot" + TOKEN + "/sendMessage"
    try:
        r = HTTP.post(url, json={"chat_id": chat_id, "text": text,
                                 "disable_web_page_preview": True,
                                 "parse_mode": "HTML"}, timeout=15)
        if r.ok:
            return True
        r2 = HTTP.post(url, json={"chat_id": chat_id, "text": text}, timeout=15)
        return bool(r2.ok)
    except requests.RequestException:
        log.warning("send_message failed", exc_info=True)
        return False

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669",
                               "01234567890123456789")

def parse_numbers(text):
    text = (text or "").translate(_ARABIC_DIGITS)
    tokens = [x for x in re.split(r"[\s,;،\n\t]+", text.strip()) if x]
    nums = []
    for t in tokens:
        if not re.fullmatch(r"\d+", t):
            raise ValueError("رمز غير صالح: " + t)
        n = int(t)
        if not 0 <= n <= 36:
            raise ValueError("الرقم " + str(n) + " خارج النطاق (0-36)")
        nums.append(n)
    return nums

def record_spins(chat_id, update_id, numbers):
    if _seen_update(update_id):
        return None
    user = get_user(chat_id)
    history = json.loads(user["history"])
    if len(history) < MIN_HISTORY:
        return None
    pred = json.loads(user["prediction"])
    hits, misses = user["hits"], user["misses"]
    results = []
    s1 = s2 = s3 = s4 = []
    for number in numbers:
        hit = bool(pred) and (number in pred)
        hits += 1 if hit else 0
        misses += 0 if hit else 1
        history.append(number)
        s1, s2, s3, s4, pred, _ = calculate_sectors(history)
        results.append({"number": number, "hit": hit})
    save_user(chat_id, history=history, sec1=s1, sec2=s2, sec3=s3, sec4=s4,
              prediction=pred, hits=hits, misses=misses)
    _mark_update(update_id)
    return {"results": results, "new_s1": s1, "new_s2": s2,
            "new_s3": s3, "new_s4": s4, "new_pred": pred,
            "hits": hits, "misses": misses}

def help_message():
    return ("🎯 <b>بوت التحليل الإحصائي للروليت V24</b>\n\n"
            "⚠️ <b>حقيقة يجب أن تعرفها:</b> لفات العجلة العادلة أحداث مستقلة ومتساوية\n"
            "الاحتمال. لا يوجد أي كود — ولا يمكن أن يوجد — يعرف الرقم القادم.\n"
            "من يبيع لك «تنبؤاً» يبيعك وهماً.\n\n"
            "✅ <b>ما يفعله هذا البوت فعلاً:</b>\n"
            "• تغطية 20 رقماً بترتيب احتمالي متسق (معدل إصابة متوقع 54.05%)\n"
            "• اختبار كاي مربع لكشف انحياز العجلة الفيزيائي (الحافة الحقيقية الوحيدة)\n"
            "• اختبار خلفي بلا استشراف + قيمة احتمالية لصدق أي تفوق\n"
            "• كشف حافة الكازينو الحقيقية: 2.70%-\n\n"
            "<b>الاستخدام:</b>\n"
            "1. أرسل 100 رقم على الأقل لتفعيل التحليل.\n"
            "2. كل رقم جديد يُقيَّم ويُحدَّث فوراً.\n\n"
            "/status - القطاعات الأربعة الحالية\n"
            "/stats - الدقة الحقيقية مع القيمة الاحتمالية\n"
            "/backtest - اختبار خلفي (بلا استشراف)\n"
            "/bias - كشف انحياز العجلة (يحتاج 1000+ لفة)\n"
            "/ev - حساب حافة الكازينو\n"
            "/start - إعادة تعيين | /help - مساعدة")

def fmt_sectors(s1, s2, s3, s4):
    return ("🔵 <b>القطاع 1:</b> <code>" + str(s1) + "</code>\n"
            "🟢 <b>القطاع 2:</b> <code>" + str(s2) + "</code>\n"
            "🟡 <b>القطاع 3:</b> <code>" + str(s3) + "</code>\n"
            "🟣 <b>القطاع 4:</b> <code>" + str(s4) + "</code>")

def status_message(user, history):
    s1 = json.loads(user["sec1"]); s2 = json.loads(user["sec2"])
    s3 = json.loads(user["sec3"]); s4 = json.loads(user["sec4"])
    return ("📊 <b>الأهداف الـ 20</b>\nآخر رقم: <b>"
            + (str(history[-1]) if history else "لا يوجد") + "</b>\n"
            + ("حجم السجل: <b>" + str(len(history)) + "</b>\n\n" if history else "\n")
            + fmt_sectors(s1, s2, s3, s4)
            + "\n\n<i>معدل الإصابة المتوقع عشوائياً: 54.05%</i>")

def stats_message(user):
    h, m = user["hits"], user["misses"]
    tot = h + m
    if tot == 0:
        return "📈 لا توجد لفات مُقيَّمة بعد. أرسل 100 رقم للتفعيل ثم أرقاماً جديدة."
    rate = h / float(tot)
    p0 = COVER_N / float(N_NUMBERS)
    pval = binomial_two_sided_p(h, tot, p0)
    lo, hi = wilson_ci(h, tot)
    verdict = ("نتيجتك متوافقة تماماً مع الصدفة — لا يوجد تفوق إحصائي."
               if pval >= 0.05 else
               "الفرق معنوي إحصائياً (p < 0.05) — راجع حجم العينة قبل أي استنتاج.")
    return ("📈 <b>الدقة الحقيقية</b>\n"
            "لفات مُقيَّمة: <b>" + str(tot) + "</b> | إصابات: <b>" + str(h) + "</b>\n"
            "الدقة: <b>" + format(rate * 100, ".1f") + "%</b>\n"
            "المتوقع عشوائياً: <b>" + format(p0 * 100, ".2f") + "%</b>\n"
            "فترة الثقة 95%: <b>" + format(lo * 100, ".1f") + "% – " + format(hi * 100, ".1f") + "%</b>\n"
            "القيمة الاحتمالية: <b>p = " + format(pval, ".3f") + "</b>\n"
            "الفرق: <b>" + format((rate - p0) * 100, "+.1f") + "%</b>\n\n" + verdict)

def backtest_message(history):
    res = walk_forward_backtest(history, COVER_N, 200)
    if res is None:
        return "السجل غير كافٍ للاختبار الخلفي (يحتاج 120 رقماً على الأقل)."
    gap = (res["acc"] - res["expected"]) * 100
    if res["p_value"] >= 0.05:
        verdict = "لا تفوق إحصائي: النموذج يطابق الصدفة. هذا هو المتوقع لعجلة عادلة."
    else:
        verdict = "فرق معنوي إحصائياً — تحقق من ثباته على عيّنة أطول ومن سلامة العجلة."
    return ("🧪 <b>اختبار خلفي بدون استشراف</b> (آخر " + str(res["total"]) + " لفة)\n"
            "إصابات: <b>" + str(res["hits"]) + "/" + str(res["total"]) + "</b>\n"
            "دقة النموذج: <b>" + format(res["acc"] * 100, ".1f") + "%</b>\n"
            "المتوقع عشوائياً: <b>" + format(res["expected"] * 100, ".2f") + "%</b>\n"
            "فترة الثقة 95%: <b>" + format(res["ci_low"] * 100, ".1f") + "% – " + format(res["ci_high"] * 100, ".1f") + "%</b>\n"
            "القيمة الاحتمالية: <b>p = " + format(res["p_value"], ".3f") + "</b>\n"
            "الفرق: <b>" + format(gap, "+.1f") + "%</b>\n\n" + verdict)

def bias_message(history):
    res = bias_test(history, MIN_SPINS_BIAS)
    if res is None:
        return ("🔬 كشف الانحياز يحتاج " + str(MIN_SPINS_BIAS)
                + " لفة على الأقل (لديك " + str(len(history)) + ").\n"
                "الأسباب: انحياز العجلة إن وُجد يكون صغيراً جداً، ويحتاج عيّنة كبيرة لكشفه.")
    if res["significant"]:
        verdict = ("⚠️ يوجد دليل إحصائي على انحياز فيزيائي (p < 0.05).\n"
                   "هذه هي الحالة الوحيدة التي يمكن فيها وجود حافة حقيقية — تحقق من سلامة العجلة.")
    else:
        verdict = ("✅ لا دليل على انحياز: التوزيع متوافق مع عجلة عادلة.\n"
                   "لا توجد حافة يمكن استغلالها إحصائياً.")
    return ("🔬 <b>اختبار انحياز العجلة (كاي مربع)</b>\n"
            "عدد اللفات: <b>" + str(res["n"]) + "</b>\n"
            "المتوقع لكل رقم: <b>" + format(res["expected"], ".1f") + "</b>\n"
            "الأكثر تكراراً: <b>" + str(res["most"]) + "</b> (" + str(res["most_count"]) + " مرة)\n"
            "الأقل تكراراً: <b>" + str(res["least"]) + "</b> (" + str(res["least_count"]) + " مرة)\n"
            "أكثر قطاع حرارة: <code>" + str(res["hot_window"]) + "</code> بحجم <b>"
            + str(res["hot_window_count"]) + " (z = " + format(res["hot_window_z"], "+.2f") + ")</b>\n"
            "كاي مربع: <b>" + format(res["chi2"], ".1f") + "</b> (الحد الحرج 5% = "
            + format(res["critical"], ".1f") + ")\n"
            "القيمة الاحتمالية: <b>p = " + format(res["p_value"], ".4f") + "</b>\n\n" + verdict)

def ev_message():
    p0 = COVER_N / float(N_NUMBERS)
    ev = p0 * 36 - COVER_N
    return ("💰 <b>حافة الكازينو الحقيقية</b>\n\n"
            "رهان على 20 رقماً (وحدة لكل رقم):\n"
            "• التكلفة: <b>" + str(COVER_N) + "</b> وحدة\n"
            "• احتمال الفوز: <b>" + format(p0 * 100, ".2f") + "%</b>\n"
            "• العائد: <b>36</b> وحدة\n"
            "• القيمة المتوقعة: <b>" + format(ev, "+.2f") + "</b> وحدة لكل رهان\n\n"
            "النسبة: <b>" + format(ev / COVER_N * 100, "+.2f") + "%</b> لكل دورة\n"
            "على 1000 رهان بهذا الحجم: خسارة متوقعة <b>"
            + format(abs(ev) * 1000, ".0f") + " وحدة</b>.\n\n"
            "هذه الحافة محسوبة رياضياً على العجلة الأوروبية 37 رقماً"
            " (1/37 = 2.70%). رفعها يقتل حسابات البائعين، ويغيرها الانحياز الفيزيائي فقط.")

def process_message(message, update_id):
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = (message.get("text") or "").strip()
    if not chat_id or not text:
        return
    if text in ("/start", "/help"):
        if text == "/start":
            reset_user(chat_id)
        send_message(chat_id, help_message())
        return
    user = get_user(chat_id)
    history = json.loads(user["history"])
    if text == "/status":
        send_message(chat_id, status_message(user, history))
        return
    if text == "/stats":
        send_message(chat_id, stats_message(user))
        return
    if text == "/backtest":
        send_message(chat_id, backtest_message(history))
        return
    if text == "/bias":
        send_message(chat_id, bias_message(history))
        return
    if text == "/ev":
        send_message(chat_id, ev_message())
        return
    try:
        numbers = parse_numbers(text)
    except ValueError as e:
        send_message(chat_id, "⚠️ " + str(e))
        return
    if not numbers:
        return
    if len(history) < MIN_HISTORY:
        if len(numbers) >= MIN_HISTORY:
            s1, s2, s3, s4, pred, _ = calculate_sectors(numbers)
            save_user(chat_id, history=numbers, sec1=s1, sec2=s2, sec3=s3,
                      sec4=s4, prediction=pred, hits=0, misses=0)
            send_message(chat_id, "✅ <b>تم تفعيل التحليل</b>\nحجم السجل: <b>"
                         + str(len(numbers)) + "</b>\nآخر رقم: <b>" + str(numbers[-1])
                         + "</b>\n\n" + fmt_sectors(s1, s2, s3, s4))
            return
        send_message(chat_id, "وصلني " + str(len(numbers)) + " رقم.\n"
                     "أرسل سجلاً من " + str(MIN_HISTORY)
                     + " رقم على الأقل للتفعيل، ثم أرسل كل لفة جديدة رقمياً.")
        return
    res = record_spins(chat_id, update_id, numbers)
    if res is None:
        send_message(chat_id, "⚠️ تمت معالجة هذا التحديث مسبقاً.")
        return
    lines = []
    hits = sum(1 for r in res["results"] if r["hit"])
    for r in res["results"]:
        lines.append(("🟢 <b>إصابة:</b> " if r["hit"] else "🔴 <b>رقم:</b> ") + str(r["number"]))
    body = "\n".join(lines)
    if len(res["results"]) > 1:
        body += "\n\nإصابات هذه الدفعة: <b>" + str(hits) + "/" + str(len(res["results"])) + "</b>"
    send_message(chat_id, body + "\n\n🎯 <b>الأهداف الجديدة الـ 20:</b>\n"
                 + fmt_sectors(res["new_s1"], res["new_s2"], res["new_s3"], res["new_s4"]))

@app.get("/")
@app.get("/health")
def home():
    return "Roulette V24 statistical analyzer is running.", 200

@app.post("/telegram-webhook")
def webhook():
    if WEBHOOK_SECRET:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(token, WEBHOOK_SECRET):
            abort(403)
    upd = request.get_json(silent=True)
    if not isinstance(upd, dict):
        return "ok", 200
    msg = upd.get("message")
    if not isinstance(msg, dict):
        return "ok", 200
    try:
        process_message(msg, str(upd.get("update_id", time.time_ns())))
    except Exception:
        log.exception("Error processing webhook update")
    return "ok", 200

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
