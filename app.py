import streamlit as st

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
    total_no_green = red + black
    red_pct = (red / total_no_green * 100) if total_no_green else 0
    black_pct = (black / total_no_green * 100) if total_no_green else 0
    return data, red, black, green, red_pct, black_pct

st.set_page_config(page_title="Roulette Report", layout="centered")
st.title("📊 تقرير شامل")

# ادخل الأرقام هنا مفصولة بمسافة أو فاصلة
text = st.text_area("دخل الأرقام - آخر رقم هو آخر لفة", "24 4 33 21 25 35 0 11 17")

if st.button("احسب التقرير"):
    try:
        spins = [int(x) for x in text.replace(",", " ").split()]
    except:
        st.error("تأكد الأرقام صح")
        spins = []

    if spins:
        last_num = spins[-1]

        # --- آخر 200 ---
        _, r200, b200, g200, _, _ = get_report(spins, 200)
        total200 = len(spins[-200:])

        st.markdown(f"### 📊 تقرير شامل (آخر {total200} لفة):")
        st.markdown(f"🔴 الأحمر: {r200} مرة ({r200/total200*100:.1f}%)")
        st.markdown(f"⚫ الأسود: {b200} مرة ({b200/total200*100:.1f}%)")
        st.markdown(f"🟢 الصفر: {g200} مرة ({g200/total200*100:.1f}%)")
        st.markdown(f"🎯 آخر رقم طاح: {last_num}")

        # --- التوازن ---
        st.markdown("### ⚖️ نسب التوازن (أحمر / أسود):")

        for window, label in [(200, "آخر 200 لفة"), (50, "آخر 50 لفة")]:
            _, r, b, g, rp, bp = get_report(spins, window)
            st.markdown(f"**📊 {label}:**")
            st.markdown(f"   🔴 الأحمر: {r} ({rp:.1f}%)")
            st.markdown(f"   ⚫ الأسود: {b} ({bp:.1f}%)")
            st.markdown(f"   🟢 الصفر: {g}")

            diff = abs(rp - bp)
            if diff < 5:
                st.markdown("   ⚖️ متوازن")
            elif rp > bp:
                st.markdown(f"   🔴 الأحمر متقدم (+{diff:.1f}%)")
            else:
                st.markdown(f"   ⚫ الأسود متقدم (+{diff:.1f}%)")

        # --- التوصية ---
        _, r50, b50, _, rp50, bp50 = get_report(spins, 50)
        st.markdown("### 💡 التوصية (آخر 50):")
        if rp50 > bp50:
            st.markdown(f"⚫ الأسود أقل — مرشح للتعويض.")
        elif bp50 > rp50:
            st.markdown(f"🔴 الأحمر أقل — مرشح للتعويض.")
        else:
            st.markdown("⚖️ متوازن - لا توجد توصية")
