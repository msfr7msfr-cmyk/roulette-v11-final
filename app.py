# V23 - تركيز 5 ارقام فقط
def get_top5_v23(history, gap_dict):
    """
    history: list من الاقدم للاحدث، اخر رقم هو 35
    gap_dict: dict يحسب كم لفة صار للرقم ما طالع
    """
    last_20 = history[-20:]
    last_5 = history[-5:]

    scores = {}
    for i, num in enumerate(last_20):
        # وزن زمني: الاحدث وزنه اكبر
        weight = 1 + (i / 20) # من 1 الى 2
        # وزن اللحظة x2 اذا باخر 5
        if num in last_5:
            weight *= 2

        scores[num] = scores.get(num, 0) + weight

    # 1. فلتر البارد القاتل
    filtered_scores = {}
    for num, score in scores.items():
        if gap_dict.get(num, 0) <= 18: # اذا صارله اكثر من 18 لفة مستبعد
            filtered_scores[num] = score

    # 2. ترتيب واخذ Top 5
    top5 = sorted(filtered_scores, key=lambda x: filtered_scores[x], reverse=True)[:5]

    return top5

# الاستخدام:
# الاساسي = top5 مباشرة (بدون ثابت 4 لفات)
# القطاع = فقط للدخول: if sector_count >= 10 -> دخول ✅
# الجيران = جيران حية فقط للـ top5 الي Gap<10
