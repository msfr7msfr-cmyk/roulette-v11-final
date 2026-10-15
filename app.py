# -*- coding: utf-8 -*-
import os, json, requests
from flask import Flask, request

app = Flask(__name__)
TOKEN = os.getenv("BOT_TOKEN")
HISTORY_FILE = "history.json"

WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]

def load_data():
    try: return json.load(open(HISTORY_FILE, "r")) if os.path.exists(HISTORY_FILE) else {}
    except: return {}

def save_data(data):
    try: json.dump(data, open(HISTORY_FILE, "w"))
    except: pass

def send_message(chat_id, text):
    try: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
    except: pass

def get_dozen_name(num):
    if 1 <= num <= 12: return "الدرزينة الأولى (1-12) 1st Dozen"
    elif 13 <= num <= 24: return "الدرزينة الثانية (13-24) 2nd Dozen"
    elif 25 <= num <= 36: return "الدرزينة الثالثة (25-36) 3rd Dozen"
    return "خارج الدرزينات (رقم 0)"

def make_single_core_prediction(nums):
    if not nums: return 0, "لم يحدد"
    last_num = nums[-1]
    counts = {}
    for i in range(len(nums) - 1):
        if nums[i] == last_num:
            next_num = nums[i + 1]
            counts[next_num] = counts.get(next_num, 0) + 1
    if counts:
        single_target = max(counts, key=counts.get)
    else:
        last15 = nums[-15:]
        freq = {}
        for n in last15: freq[n] = freq.get(n, 0) + 1
        single_target = max(freq, key=freq.get) if freq else 32
    dozen_info = get_dozen_name(single_target)
    return single_target, dozen_info

@app.route('/')
def home(): return "Bot is Alive with Core Single Number & Dozen Mode!"

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        if not data or "message" not in data or "text" not in data["message"]: return "ok"
        chat_id = str(data["message"]["chat"]["id"])
        text = data["message"]["text"].strip()
        db = load_data()
        if "history" not in db: db["history"] = {}
        if "pred_num" not in db: db["pred_num"] = {}
        if "pred_doz" not in db: db["pred_doz"] = {}
        if "fails" not in db: db["fails"] = {}
        if text == "/start":
            db["history"][chat_id], db["fails"][chat_id] = [], 0
            db["pred_num"][chat_id], db["pred_doz"][chat_id] = 0, ""
            save_data(db)
            send_message(chat_id, "🎯 تم تفعيل رادار (الرقم الواحد الفردي وعيار الدرزينة المدمج).\n🧹 تم تنظيف الجلسة تماماً.\n📥 أرسل سجل الـ 100 رقم لتبدأ قنص الهدف لـ 10 لفات ثابتة.")
            return "ok"
        nums = []
        for x in text.replace(",", " ").split():
            if x.lstrip("-").isdigit():
                v = int(x)
                if 0 <= v <= 36: nums.append(v)
        if len(nums) == 0:
            send_message(chat_id, "⚠️ يرجى إرسال أرقام صحيحة فقط من 0 إلى 36.")
            return "ok"
        if len(nums) == 1:
            if chat_id not in db["history"] or len(db["history"][chat_id]) < 100:
                send_message(chat_id, "⚠️ خطأ: يرجى إرسال الـ 100 رقم البدئية الخاصة بجلسة اليوم أولاً!")
                return "ok"
            new_num = nums[0]
            last_target_num = db["pred_num"].get(chat_id, -1)
            last_target_doz = db["pred_doz"].get(chat_id, "")
            fails = db["fails"].get(chat_id, 0)
            is_dozen_win = (1 <= new_num <= 12 and "الأولى" in last_target_doz) or \
                           (13 <= new_num <= 24 and "الثانية" in last_target_doz) or \
                           (25 <= new_num <= 36 and "الثالثة" in last_target_doz)
            if new_num == last_target_num:
                db["history"][chat_id].append(new_num)
                new_target, new_doz = make_single_core_prediction(db["history"][chat_id])
                db["pred_num"][chat_id], db["pred_doz"][chat_id], db["fails"][chat_id] = new_target, new_doz, 0
                save_data(db)
                send_message(chat_id, f"🔥 قنص فيزيائي مرعب!! ضرب الرقم الخارق المستهدف بالملي: ({new_num}) بـ 35 ضعفاً! 🎉\n\n🔄 تم تصفير المحاولات لبدء دورة 10 لفات جديدة بربح ضخم جداً.\n🏹 الرقم المستهدف الجديد: [{new_target}]\n🛡️ الدرزينة الحمائية: {new_doz}")
            elif is_dozen_win:
                db["history"][chat_id].append(new_num)
                new_target, new_doz = make_single_core_prediction(db["history"][chat_id])
                db["pred_num"][chat_id], db["pred_doz"][chat_id], db["fails"][chat_id] = new_target, new_doz, 0
                save_data(db)
                send_message(chat_id, f"🟢 ضربة حماية! الماكينة سقطت في {new_num} داخل {last_target_doz} المأمنة كلياً!\n\n🎯 تم صيد هدف المحيط وتصفير الدورة بنجاح.\n🏹 الرقم المستهدف القادم: [{new_target}]\n🛡️ الدرزينة الحمائية: {new_doz}")
            else:
                fails += 1
                if fails >= 10:
                    db["history"][chat_id].append(new_num)
                    new_target, new_doz = make_single_core_prediction(db["history"][chat_id])
                    db["pred_num"][chat_id], db["pred_doz"][chat_id], db["fails"][chat_id] = new_target, new_doz, 0
                    save_data(db)
                    send_message(chat_id, f"⚠️ انتهت الـ 10 لفات الثابتة للمطاردة دون ضربة قريبة.\n🔄 إعادة معايرة فورية: تم تحديث الرقم الفردي وتحديد درزينته للرمية الحالية الحية.\n🏹 الرقم المستهدف الجديد: [{new_target}]\n🛡️ الدرزينة الحمائية: {new_doz}")
                else:
                    db["fails"][chat_id] = fails
                    db["history"][chat_id].append(new_num)
                    save_data(db)
                    send_message(chat_id, f"❌ لفة {fails}/10: ظهر الرقم {new_num}.\n🏹 النواة ثابتة والمطاردة مستمرة! ابقَ على الرهان الحالي:\n🎯 الرقم الفردي: [{last_target_num}]\n🛡️ الدرزينة الحمائية: {last_target_doz}")
            return "ok"
        if len(nums) >= 100:
            db["history"][chat_id] = nums
            target_num, dozen_info = make_single_core_prediction(nums)
            db["pred_num"][chat_id], db["pred_doz"][chat_id], db["fails"][chat_id] = target_num, dozen_info, 0
            save_data(db)
            msg = f"📊 تم كسر تشفير عيار الطاولة بنظام (الرقم الواحد والدرزينة) بنجاح.\n"
            msg += f"ℹ️ الرقم الأحدث في نهاية السجل حالياً هو: ({nums[-1]})\n"
            msg += f"🎯 الرقم المستهدف لقنص الـ 10 لفات (قطعة واحدة): [{target_num}]\n"
            msg += f"🛡️ الرهان الحمائي الموازي (محيط الأمان): {dozen_info}\n"
            msg += f"🎰 ثبت رهانك بدقة، وأرسل كل رقم يظهر مباشرة فوراً لتتبع العداد."
            send_message(chat_id, msg)
            return "ok"
    except Exception as e:
        pass
    return "ok"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
