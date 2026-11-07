from flask import Flask, request, render_template_string

app = Flask(__name__)

RED = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]

def color(n):
    if n == 0:
        return "green"
    if n in RED:
        return "red"
    return "black"

def get_report(spins, window):
    data = spins[-window:]
    red = sum(1 for n in data if color(n) == "red")
    black = sum(1 for n in data if color(n) == "black")
    green = sum(1 for n in data if color(n) == "green")
    total = len(data)
    total_no_green = red + black
    rp = (red / total_no_green * 100) if total_no_green else 0
    bp = (black / total_no_green * 100) if total_no_green else 0
    return red, black, green, total, rp, bp

HTML = """
<h2>📊 تقرير شامل</h2>
<form method="POST">
<textarea name="nums" rows="4" cols="40" placeholder="دخل الأرقام - آخر رقم هو آخر لفة">{{ nums }}</textarea><br><br>
<button type="submit">احسب التقرير</button>
</form>
{% if spins %}
<hr>
<h3>📊 تقرير شامل (آخر {{total200}} لفة):</h3>
<p>🔴 الأحمر: {{r200}} مرة ({{'%.1f'|format(r200/total200*100)}}%)</p>
<p>⚫ الأسود: {{b200}} مرة ({{'%.1f'|format(b200/total200*100)}}%)</p>
<p>🟢 الصفر: {{g200}} مرة ({{'%.1f'|format(g200/total200*100)}}%)</p>
<p>🎯 آخر رقم طاح: {{last}}</p>
<h3>⚖️ نسب التوازن</h3>
<p><b>📊 آخر 200:</b> 🔴 {{r200}} ({{'%.1f'|format(rp200)}}%) | ⚫ {{b200}} ({{'%.1f'|format(bp200)}}%) | 🟢 {{g200}}</p>
<p><b>📊 آخر 50:</b> 🔴 {{r50}} ({{'%.1f'|format(rp50)}}%) | ⚫ {{b50}} ({{'%.1f'|format(bp50)}}%) | 🟢 {{g50}}</p>
<h3>💡 التوصية (آخر 50):</h3>
<p>{{reco}}</p>
{% endif %}
"""

@app.route("/", methods=["GET", "POST"])
def index():
    nums = ""
    data = {}
    if request.method == "POST":
        nums = request.form.get("nums", "")
        try:
            spins = [int(x) for x in nums.replace(",", " ").split()]
        except:
            spins = []
        if spins:
            r200, b200, g200, total200, rp200, bp200 = get_report(spins, 200)
            r50, b50, g50, _, rp50, bp50 = get_report(spins, 50)
            if rp50 > bp50:
                reco = "⚫ الأسود أقل — مرشح للتعويض."
            elif bp50 > rp50:
                reco = "🔴 الأحمر أقل — مرشح للتعويض."
            else:
                reco = "⚖️ متوازن - لا توجد توصية"
            data = dict(spins=True, r200=r200, b200=b200, g200=g200, total200=total200,
                        r50=r50, b50=b50, g50=g50, rp200=rp200, bp200=bp200, rp50=rp50, bp50=bp50,
                        last=spins[-1], reco=reco)
    return render_template_string(HTML, nums=nums, **data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
