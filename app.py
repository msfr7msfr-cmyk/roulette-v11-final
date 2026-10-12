import numpy as np

# ============================
# BOT - Deceleration Physics Core
# ============================

class Wheel:
    """ترتيب العجلة الأوروبية"""
    ORDER = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
    POS = {n:i for i,n in enumerate(ORDER)}

class DecelerationPhysics:
    """فيزيا التباطؤ - العقل الرئيسي"""
    def __init__(self, mu=0.08, g=9.81, r=0.4):
        self.mu = mu
        self.g = g
        self.r = r
        self.alpha = mu * g / r # معدل التباطؤ الزاوي

    def calc_score(self, number, history):
        # اذا التاريخ قليل، ما يقدر يحكم
        if history is None or len(history) < 50:
            return 0.0

        # حساب التباطؤ من اخر 100 لفة
        recent = history[-100:]
        count = np.sum(np.array(recent) == number)
        expected = len(recent) / 37.0
        if expected == 0:
            return 0.0

        # قوة = العدد الفعلي / المتوقع
        strength = count / expected

        # حساب التباطؤ الفيزيائي
        # v_final = w0 - alpha * t
        # كل ما الرقم تكرر اكثر، معناه التباطؤ ثبت عليه
        # نحول القوة الى سكور
        if strength >= 1.5:
            return strength
        return strength * 0.5

    def choose(self, candidates, history):
        approved = []
        for n in candidates:
            score = self.calc_score(n, history)
            if score >= 1.5:
                approved.append((n, score))

        # ترتيب من الاقوى
        approved.sort(key=lambda x: x[1], reverse=True)

        if len(approved) < 3:
            return "انتظر"

        return [n for n,_ in approved[:3]]

class DropPointTool:
    """اداة موعد النزول"""
    def get_candidates(self, history):
        # ترجع القطاع الاكثر تكرارا في اخر 100
        if len(history) < 50:
            return []
        recent = history[-100:]
        vals, counts = np.unique(recent, return_counts=True)
        idx = np.argsort(-counts)[:9]
        return vals[idx].tolist()

class WheelSpeedTool:
    """اداة سرعة العجلة"""
    def get_candidates(self, history):
        if len(history) < 10:
            return []
        last = history[-1]
        p = Wheel.POS[last]
        # 3 ارقام بعد 8 جيوب
        return [Wheel.ORDER[(p+8+d)%37] for d in [-1,0,1]]

class BounceTool:
    """اداة الارتداد"""
    def get_candidates(self, history):
        if len(history) < 10:
            return []
        last = history[-1]
        p = Wheel.POS[last]
        return [Wheel.ORDER[(p+6+d)%37] for d in [-1,0,1]]

class Bot:
    """البوت الرئيسي"""
    def __init__(self):
        self.physics = DecelerationPhysics()
        self.tools = {
            "drop": DropPointTool(),
            "speed": WheelSpeedTool(),
            "bounce": BounceTool(),
        }
        self.history = []

    def add_result(self, number):
        self.history.append(number)

    def decide(self):
        # 1. اجمع اقتراحات كل الادوات
        all_candidates = []
        for tool in self.tools.values():
            all_candidates.extend(tool.get_candidates(self.history))

        # ازالة التكرار
        candidates = list(set(all_candidates))

        if len(candidates) == 0:
            return "انتظر"

        # 2. مررها على فيزيا التباطؤ
        result = self.physics.choose(candidates, self.history)

        # 3. اذا التباطؤ قال انتظر، البوت يقول انتظر، ما يخمن
        return result

    def status(self):
        if len(self.history) < 50:
            return f"انتظر - عندي {len(self.history)} لفة فقط، احتاج 50+"
        return f"جاهز - {len(self.history)} لفة"

# ============================
# التشغيل
# ============================
if __name__ == "__main__":
    bot = Bot()

    # مثال: ادخل ارقامك هنا بالترتيب
    sample_data = [17,16,29,10,31,0,21,32,19,4] # ضع ارقامك الحقيقية هنا

    for num in sample_data:
        bot.add_result(num)

    print(bot.status())
    print("قرار البوت:", bot.decide())

    # لايف: كل ما يجي رقم جديد
    # bot.add_result(19)
    # print(bot.decide())
