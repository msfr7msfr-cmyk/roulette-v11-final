# -*- coding: utf-8 -*-
"""Conservative walk-forward roulette bot - single file"""
from __future__ import annotations
import hmac, html, json, logging, math, os, re, sqlite3, time, unicodedata
from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any
import requests
from flask import Flask, abort, request

# ============ CONFIG ============
TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DB_FILE = os.getenv("DATABASE_PATH", "roulette.sqlite3")

app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("roulette_bot")
HTTP = requests.Session()
if not WEBHOOK_SECRET:
    log.warning("WEBHOOK_SECRET is unset")

# ============ MODEL ============
WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
WHEEL_SIZE = 37
WHEEL_INDEX = {n:i for i,n in enumerate(WHEEL)}
MIN_HISTORY = 100
MIN_BACKTEST_SPINS = 30
RANDOM_TOP20_RATE = 20 / WHEEL_SIZE

def _validated(history: Sequence[int]) -> list[int]:
    values = list(history)
    if any(type(v) is not int or v not in WHEEL_INDEX for v in values):
        raise ValueError("history must contain only 0-36")
    return values

def parse_numbers(text: str) -> list[int]:
    normalized = "".join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in text.strip())
    tokens = [t for t in re.split(r"[\s,;،؛|]+", normalized) if t]
    nums: list[int] = []
    for token in tokens:
        if not re.fullmatch(r"\d{1,2}", token):
            raise ValueError(f"خطأ في الرمز: {token}")
        number = int(token)
        if number not in WHEEL_INDEX:
            raise ValueError(f"الرقم {number} خارج نطاق الروليت (0-36)")
        nums.append(number)
    return nums

def _uniform() -> list[float]:
    return [1 / WHEEL_SIZE] * WHEEL_SIZE

def _normalize(values: Sequence[float]) -> list[float]:
    total = sum(values)
    if not math.isfinite(total) or total <= 0:
        return _uniform()
    return [max(0.0, v) / total for v in values]

def wheel_dist(a: int, b: int) -> int:
    d = abs(WHEEL_INDEX[a] - WHEEL_INDEX[b]) % WHEEL_SIZE
    return min(d, WHEEL_SIZE - d)

def wheel_step(a: int, b: int) -> int:
    s = (WHEEL_INDEX[b] - WHEEL_INDEX[a]) % WHEEL_SIZE
    if s > WHEEL_SIZE / 2: s -= WHEEL_SIZE
    return int(s)

def neighbors(center: int, radius: int = 2) -> list[int]:
    idx = WHEEL_INDEX[center]
    return [WHEEL[(idx + o) % WHEEL_SIZE] for o in range(-radius, radius + 1)]

def _decay_weights(count: int, halflife: float) -> list[float]:
    if count <= 0: return []
    if halflife <= 0: raise ValueError("halflife must be positive")
    return [0.5 ** ((count - 1 - i) / halflife) for i in range(count)]

def _score_frequency(history, lookback=250, halflife=None, prior_mass=80.0):
    values = _validated(history)
    recent = values[-max(0, lookback):] if lookback else []
    weights = _decay_weights(len(recent), halflife) if halflife else [1.0] * len(recent)
    counts = [0.0] * WHEEL_SIZE
    for n,w in zip(recent, weights): counts[n] += w
    prior = prior_mass / WHEEL_SIZE
    denom = sum(counts) + prior_mass
    if denom <= 0: return _uniform()
    return [(c + prior) / denom for c in counts]

def _score_neighbor_affinity(history, lookback=120):
    values = _validated(history)
    recent = values[-lookback:]
    if not recent:
        u = _uniform(); return u, u[:]
    weights = _decay_weights(len(recent), 35.0)
    n1 = [0.0]*WHEEL_SIZE; n2=[0.0]*WHEEL_SIZE
    for n,w in zip(recent, weights):
        idx = WHEEL_INDEX[n]
        for off in (-1,0,1): n1[WHEEL[(idx+off)%WHEEL_SIZE]] += w
        for off in (-2,-1,0,1,2): n2[WHEEL[(idx+off)%WHEEL_SIZE]] += w
    prior = 90.0 / WHEEL_SIZE
    return _normalize([v+prior for v in n1]), _normalize([v+prior for v in n2])

def _score_step_distribution(history, lookback=250):
    values = _validated(history)
    if len(values) < 25: return _uniform()
    recent = values[-lookback:]
    steps = [wheel_step(recent[i-1], recent[i]) for i in range(1,len(recent))]
    counts = Counter(steps)
    prior = 110.0 / WHEEL_SIZE
    last = values[-1]
    return _normalize([counts.get(wheel_step(last,c),0)+prior for c in range(WHEEL_SIZE)])

def _score_direction(history, lookback=80):
    values = _validated(history)
    if len(values) < 5: return 0.5,0.5
    recent = values[-lookback:]
    steps = [wheel_step(recent[i-1], recent[i]) for i in range(1,len(recent))]
    nz = [s for s in steps if s]
    if not nz: return 0.5,0.5
    cw = sum(s>0 for s in nz)
    return (cw+12)/(len(nz)+24), (len(nz)-cw+12)/(len(nz)+24)

def _score_markov_advanced(history, lookback=500):
    values = _validated(history)
    base = _score_frequency(values, lookback=lookback, prior_mass=100.0)
    if len(values) < 40: return base
    recent = values[-lookback:]
    fo: dict[int, Counter[int]] = defaultdict(Counter)
    so: dict[tuple[int,int], Counter[int]] = defaultdict(Counter)
    for i in range(1,len(recent)):
        fo[recent[i-1]][recent[i]] += 1
        if i>=2: so[(recent[i-2], recent[i-1])][recent[i]] += 1
    pair = so.get((values[-2], values[-1]), Counter())
    one = fo.get(values[-1], Counter())
    if sum(pair.values()) >= 4: row = pair
    elif sum(one.values()) >= 25: row = one
    else: return base
    prior_mass = 120.0
    total = sum(row.values()) + prior_mass
    return _normalize([(row.get(n,0)+prior_mass*base[n])/total for n in range(WHEEL_SIZE)])

def _score_hot_sectors(history, lookback=120, sector_size=5):
    values = _validated(history)
    if not values: return _uniform()
    radius = max(0, sector_size//2)
    recent = values[-lookback:]
    weights = _decay_weights(len(recent), 40.0)
    act = [0.0]*WHEEL_SIZE
    for n,w in zip(recent, weights):
        for c in neighbors(n, radius): act[c] += w/(2*radius+1)
    prior = 100.0 / WHEEL_SIZE
    return _normalize([v+prior for v in act])

def _expert_scores(history):
    values = _validated(history)
    uniform = _uniform()
    if not values:
        return {name: uniform[:] for name in ("uniform","recent","long","decay","near1","near2","step","markov","sector")}
    n1,n2 = _score_neighbor_affinity(values)
    return {
        "uniform": uniform,
        "recent": _score_frequency(values, lookback=70, prior_mass=75.0),
        "long": _score_frequency(values, lookback=350, prior_mass=100.0),
        "decay": _score_frequency(values, lookback=180, halflife=55.0, prior_mass=90.0),
        "near1": n1, "near2": n2,
        "step": _score_step_distribution(values),
        "markov": _score_markov_advanced(values),
        "sector": _score_hot_sectors(values),
    }

def _online_model_weights(history, calibration_window=100):
    values = _validated(history)
    names = tuple(_expert_scores(values[:0]).keys())
    priors = {name: (0.35 if name=="uniform" else 0.65/(len(names)-1)) for name in names}
    hits = {name:0 for name in names}
    start = max(40, len(values)-calibration_window)
    observed = 0
    for ti in range(start, len(values)):
        forecasts = _expert_scores(values[:ti])
        outcome = values[ti]
        for name in names:
            top = sorted(range(WHEEL_SIZE), key=lambda n: (-forecasts[name][n], WHEEL_INDEX[n]))[:20]
            hits[name] += outcome in top
        observed += 1
    expected = observed * RANDOM_TOP20_RATE
    sd = math.sqrt(max(1e-12, observed * RANDOM_TOP20_RATE * (1-RANDOM_TOP20_RATE)))
    evidence = {name: max(-3.0, min(3.0, (hits[name]-expected)/sd)) if observed else 0.0 for name in names}
    eta = 0.45
    logits = {name: math.log(priors[name]) + eta*evidence[name] for name in names}
    peak = max(logits.values())
    learned = {name: math.exp(v-peak) for name,v in logits.items()}
    total = sum(learned.values())
    learned = {name: v/total for name,v in learned.items()}
    weights = {name: 0.70*learned[name] for name in names}
    weights["uniform"] += 0.30
    return weights

def _combine_scores(history):
    values = _validated(history)
    experts = _expert_scores(values)
    weights = _online_model_weights(values)
    return _normalize([sum(weights[name]*forecast[n] for name,forecast in experts.items()) for n in range(WHEEL_SIZE)])

def _select_top20(history, scores, top_n=20):
    _validated(history)
    if len(scores)!=WHEEL_SIZE: raise ValueError("scores must contain 37")
    return sorted(range(WHEEL_SIZE), key=lambda n: (-scores[n], WHEEL_INDEX[n]))[:top_n]

def calculate_v23(history):
    values = _validated(history)
    ranking = _select_top20(values, _combine_scores(values), top_n=20)
    groups = [ranking[i:i+5] for i in range(0,20,5)]
    return groups[0], groups[1], groups[2], groups[3], ranking

def wilson_interval(successes, total, z=1.959963984540054):
    if total<=0: return 0.0,0.0
    rate = successes/total
    z2=z*z; denom=1+z2/total
    center=(rate+z2/(2*total))/denom
    margin=z*math.sqrt((rate*(1-rate)+z2/(4*total))/total)/denom
    return max(0.0, center-margin), min(1.0, center+margin)

def _backtest_accuracy(history, top_n=20, test_len=200):
    values = _validated(history)
    available = len(values)-MIN_HISTORY
    sample = min(test_len, available)
    if sample < MIN_BACKTEST_SPINS: return None
    hits=0; start=len(values)-sample
    for ti in range(start, len(values)):
        prefix = values[:ti]
        chosen = set(_select_top20(prefix, _combine_scores(prefix), top_n=top_n))
        hits += values[ti] in chosen
    lo,hi = wilson_interval(hits, sample)
    return {"hits":hits,"trials":sample,"rate":hits/sample,"baseline":top_n/WHEEL_SIZE,"ci_low":lo,"ci_high":hi,"above_baseline_significant": lo>top_n/WHEEL_SIZE}

# ============ DATABASE ============
def connect_db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_FILE, timeout=20); c.row_factory=sqlite3.Row; return c

def init_db() -> None:
    with connect_db() as c:
        c.execute("PRAGMA journal_mode=WAL;")
        c.executescript("""
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
            """)

def get_user(chat_id: str) -> dict[str, Any]:
    with connect_db() as c:
        row = c.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        if row is None:
            c.execute("INSERT INTO users(chat_id) VALUES(?)", (str(chat_id),))
            c.commit()
            row = c.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        return dict(row)

def save_user(chat_id: str, **values: Any) -> None:
    allowed={"history","sec1","sec2","sec3","sec4","prediction","hits","misses","total_bet"}
    jf={"history","sec1","sec2","sec3","sec4","prediction"}
    fields=[]; params=[]
    for k,v in values.items():
        if k not in allowed: continue
        if k in jf: v=json.dumps(v, ensure_ascii=False)
        fields.append(f"{k}=?"); params.append(v)
    if not fields: return
    params.append(str(chat_id))
    with connect_db() as c: c.execute(f"UPDATE users SET {', '.join(fields)} WHERE chat_id=?", params)

def reset_user(chat_id: str) -> None:
    with connect_db() as c:
        c.execute("""
            INSERT INTO users(chat_id,history,sec1,sec2,sec3,sec4,prediction,hits,misses,total_bet)
            VALUES(?, '[]','[]','[]','[]','[]','[]',0,0,0)
            ON CONFLICT(chat_id) DO UPDATE SET history='[]',sec1='[]',sec2='[]',sec3='[]',sec4='[]',prediction='[]',hits=0,misses=0,total_bet=0
            """, (str(chat_id),))

def send_message(chat_id: str, text: str) -> bool:
    if not TOKEN: return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": chat_id,"text": text,"disable_web_page_preview": True,"parse_mode": "HTML"}
    try:
        r = HTTP.post(url, json=payload, timeout=15)
        if r.ok: return True
        payload.pop("parse_mode")
        return HTTP.post(url, json=payload, timeout=15).ok
    except requests.RequestException:
        log.exception("Unable to send Telegram message."); return False

def record_spin(chat_id: str, update_id: str, number: int) -> dict[str, Any] | None:
    with connect_db() as c:
        row = c.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        if row is None: return None
        user = dict(row); history = json.loads(user["history"])
        if len(history) < MIN_HISTORY: return None
        try: c.execute("INSERT INTO updates_seen(update_id) VALUES(?)", (str(update_id),))
        except sqlite3.IntegrityError: return None
        prediction = calculate_v23(history)[4]
        hit = number in prediction
        hits = user["hits"]+int(hit); misses = user["misses"]+int(not hit)
        history.append(number)
        s1,s2,s3,s4,new_pred = calculate_v23(history)
        c.execute("UPDATE users SET history=?,sec1=?,sec2=?,sec3=?,sec4=?,prediction=?,hits=?,misses=? WHERE chat_id=?",
            (json.dumps(history), json.dumps(s1), json.dumps(s2), json.dumps(s3), json.dumps(s4), json.dumps(new_pred), hits, misses, str(chat_id)))
        return {"hit":hit,"number":number,"new_s1":s1,"new_s2":s2,"new_s3":s3,"new_s4":s4,"new_pred":new_pred,"hits":hits,"misses":misses}

def _format_list(values: list[int]) -> str:
    return html.escape("، ".join(str(v) for v in values))

def help_message() -> str:
    return (
        "<b>بوت تحليل الروليت</b>\n\n"
        "يرتّب 20 رقمًا باستخدام تكرارات مموّهة إحصائيًا، وأنماط الجوار والانتقال، "
        "ويعدّل أوزان النماذج حسب إصاباتها في توقعات سابقة متدرجة.\n"
        "الروليت العادل عشوائي؛ لا توجد طريقة تضمن معرفة الرقم القادم أو الربح.\n\n"
        "1. أرسل سجلًا تاريخيًا من 100 رقم على الأقل. يقبل الأرقام العربية والفارسية أيضًا.\n"
        "2. بعد التفعيل، أرسل رقمًا واحدًا بعد كل دورة لتحديث الاختيار والإحصاءات.\n\n"
        "/start - مسح السجل الحالي والبدء من جديد\n"
        "/status - عرض الأرقام العشرين الحالية\n"
        "/stats - عرض النتائج مقارنة بخط الأساس العشوائي\n"
        "/backtest - اختبار متدرّج على نتائج لم تُستخدم في كل توقع\n"
        "/help - المساعدة"
    )

def process_message(message: dict[str, Any], update_id: str) -> None:
    chat = message.get("chat")
    if not isinstance(chat, dict) or "id" not in chat: return
    chat_id = str(chat["id"]); text = (message.get("text") or "").strip()
    if not text: return
    if text in ("/start", "/help"):
        if text == "/start": reset_user(chat_id)
        send_message(chat_id, help_message()); return
    user = get_user(chat_id); history = json.loads(user["history"])
    if text == "/status":
        s1,s2,s3,s4,pred = calculate_v23(history) if len(history) >= MIN_HISTORY else ([],[],[],[],[])
        if len(history) < MIN_HISTORY or len(pred) != 20:
            send_message(chat_id, "أرسل سجلًا تاريخيًا من 100 رقم على الأقل لتفعيل التوقعات."); return
        h,m = int(user["hits"]), int(user["misses"]); ev = h+m
        if ev:
            lo,hi = wilson_interval(h, ev)
            measured = f"الدقة المسجلة: <b>{h}/{ev} ({h/ev*100:.1f}%)</b>\nفاصل الثقة 95%: <b>{lo*100:.1f}%–{hi*100:.1f}%</b>\n"
        else: measured = "لم تُسجّل نتائج كافية لتقييم التوقعات بعد.\n"
        send_message(chat_id, f"<b>الأرقام العشرون المختارة حاليًا</b>\nآخر رقم مسجل: <b>{history[-1]}</b>\n{measured}خط الأساس العشوائي: <b>{RANDOM_TOP20_RATE*100:.1f}%</b>\n<i>لا توجد طريقة تضمن النتيجة القادمة.</i>\n\nالمجموعة 1: <code>{_format_list(s1)}</code>\nالمجموعة 2: <code>{_format_list(s2)}</code>\nالمجموعة 3: <code>{_format_list(s3)}</code>\nالمجموعة 4: <code>{_format_list(s4)}</code>")
        return
    if text == "/stats":
        h,m = int(user["hits"]), int(user["misses"]); tot=h+m
        if tot:
            rate=h/tot; lo,hi=wilson_interval(h,tot)
            conf=f"فاصل الثقة 95%: <b>{lo*100:.1f}%–{hi*100:.1f}%</b>\n"
        else: rate=0.0; conf=""
        send_message(chat_id, f"<b>الإحصاءات الفعلية</b>\nاللفات المقيمة: <b>{tot}</b> | إصابات: <b>{h}</b> | إخفاقات: <b>{m}</b>\nنسبة الإصابة: <b>{rate*100:.1f}%</b>\n{conf}خط الأساس لاختيار 20 من 37: <b>{RANDOM_TOP20_RATE*100:.1f}%</b>\n<i>العينة القصيرة قد تبدو أعلى أو أقل من مستواها الحقيقي.</i>")
        return
    if text == "/backtest":
        res = _backtest_accuracy(history, top_n=20, test_len=200)
        if res is None:
            send_message(chat_id, f"أحتاج إلى {MIN_HISTORY+MIN_BACKTEST_SPINS} رقمًا على الأقل: 100 رقم للتدريب و30 على الأقل للاختبار."); return
        diff=(float(res["rate"])-float(res["baseline"]))*100
        concl="الحد الأدنى لفاصل الثقة تجاوز خط الأساس في هذا الاختبار." if res["above_baseline_significant"] else "لا يثبت هذا الاختبار أن النموذج يتفوّق على العشوائي."
        send_message(chat_id, f"<b>اختبار تاريخي متدرّج</b>\nاللفات المختبرة: <b>{res['trials']}</b> | الإصابات: <b>{res['hits']}</b>\nالدقة: <b>{float(res['rate'])*100:.1f}%</b>\nخط الأساس العشوائي: <b>{float(res['baseline'])*100:.1f}%</b>\nالفرق: <b>{diff:+.1f} نقطة مئوية</b>\nفاصل الثقة 95%: <b>{float(res['ci_low'])*100:.1f}%–{float(res['ci_high'])*100:.1f}%</b>\n<i>{concl} النتائج الماضية لا تضمن المستقبل.</i>")
        return
    try: numbers = parse_numbers(text)
    except ValueError as e: send_message(chat_id, f"⚠️ {html.escape(str(e))}"); return
    if not numbers: return
    if len(numbers) >= MIN_HISTORY:
        s1,s2,s3,s4,pred = calculate_v23(numbers)
        save_user(chat_id, history=numbers, sec1=s1, sec2=s2, sec3=s3, sec4=s4, prediction=pred, hits=0, misses=0)
        send_message(chat_id, f"<b>تم تسجيل السجل وتفعيل التحليل</b>\nحجم السجل: <b>{len(numbers)}</b> | آخر رقم: <b>{numbers[-1]}</b>\nخط الأساس العشوائي لاختيار 20 رقمًا: <b>{RANDOM_TOP20_RATE*100:.1f}%</b>\n<i>هذه أول قائمة؛ لا يمكن تقييم دقتها قبل تسجيل دورات لاحقة.</i>\n\nالمجموعة 1: <code>{_format_list(s1)}</code>\nالمجموعة 2: <code>{_format_list(s2)}</code>\nالمجموعة 3: <code>{_format_list(s3)}</code>\nالمجموعة 4: <code>{_format_list(s4)}</code>")
        return
    if len(numbers) != 1 or len(history) < MIN_HISTORY:
        send_message(chat_id, f"وصلني {len(numbers)} رقمًا. أرسل سجلًا تاريخيًا من {MIN_HISTORY} رقم على الأقل للبدء."); return
    res = record_spin(chat_id, update_id, numbers[0])
    if res is None: send_message(chat_id, "⚠️ السجل غير مكتمل أو سبق تسجيل هذه الدورة."); return
    label = "إصابة" if res["hit"] else "لم تصب هذه المرة"
    send_message(chat_id, f"<b>{label}: {res['number']}</b>\n\n<b>الأرقام العشرون للدورة التالية:</b>\n1: <code>{_format_list(res['new_s1'])}</code>\n2: <code>{_format_list(res['new_s2'])}</code>\n3: <code>{_format_list(res['new_s3'])}</code>\n4: <code>{_format_list(res['new_s4'])}</code>")

@app.get("/")
def home() -> tuple[str, int]: return "Roulette analysis bot is running.", 200

@app.post("/telegram-webhook")
def webhook() -> tuple[str, int]:
    if WEBHOOK_SECRET and not hmac.compare_digest(request.headers.get("X-Telegram-Bot-Api-Secret-Token", ""), WEBHOOK_SECRET): abort(403)
    update = request.get_json(silent=True)
    if not isinstance(update, dict): return "ok", 200
    message = update.get("message")
    if not isinstance(message, dict): return "ok", 200
    try: process_message(message, str(update.get("update_id", time.time_ns())))
    except Exception: log.exception("Error processing Telegram webhook update.")
    return "ok", 200

init_db()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
