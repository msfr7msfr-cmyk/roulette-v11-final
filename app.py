from flask import Flask, request, jsonify

app = Flask(__name__)

WHEEL_ORDER = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
WHEEL_POS = {n:i for i,n in enumerate(WHEEL_ORDER)}

class DecelerationPhysics:
    def __init__(self, mu=0.08, g=9.81, r=0.4):
        self.mu = mu
        self.g = g
        self.r = r
        self.alpha = mu * g / r

    def calc_score(self, number, history):
        if history is None or len(history) < 50:
            return 0.0
        recent = history[-100:]
        count = sum(1 for x in recent if x == number)
        expected = len(recent) / 37.0
        if expected == 0:
            return 0.0
        strength = count / expected
        if strength >= 1.5:
            return strength
        return strength * 0.5

    def choose(self, candidates, history):
        approved = []
        for n in candidates:
            score = self.calc_score(n, history)
            if score >= 1.5:
                approved.append((n, score))
        approved.sort(key=lambda x: x[1], reverse=True)
        if len(approved) < 3:
            return "انتظر"
        return [n for n,_ in approved[:3]]

class DropPointTool:
    def get_candidates(self, history):
        if len(history) < 50:
            return []
        recent = history[-100:]
        counts = {}
        for n in recent:
            counts[n] = counts.get(n, 0) + 1
        sorted_nums = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return [n for n,_ in sorted_nums[:9]]

class WheelSpeedTool:
    def get_candidates(self, history):
        if len(history) < 10:
            return []
        last = history[-1]
        p = WHEEL_POS[last]
        return [WHEEL_ORDER[(p+8+d)%37] for d in [-1,0,1]]

class BounceTool:
    def get_candidates(self, history):
        if len(history) < 10:
            return []
        last = history[-1]
        p = WHEEL_POS[last]
        return [WHEEL_ORDER[(p+6+d)%37] for d in [-1,0,1]]

class Bot:
    def __init__(self):
        self.physics = DecelerationPhysics()
        self.tools = [DropPointTool(), WheelSpeedTool(), BounceTool()]
        self.history = []
    def add_result(self, number):
        self.history.append(number)
    def decide(self):
        all_candidates = []
        for tool in self.tools:
            all_candidates.extend(tool.get_candidates(self.history))
        candidates = list(set(all_candidates))
        if len(candidates) == 0:
            return "انتظر"
        return self.physics.choose(candidates, self.history)

bot = Bot()

@app.route('/')
def home():
    return jsonify({"status": "Bot running", "history": len(bot.history), "decision": bot.decide()})

@app.route('/add/<int:num>')
def add(num):
    bot.add_result(num)
    return jsonify({"added": num, "decision": bot.decide()})

@app.route('/decide')
def decide():
    return jsonify({"decision": bot.decide()})

@app.route('/reset')
def reset():
    bot.history = []
    return jsonify({"status": "reset done"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
