import streamlit as st
import tempfile
import os
import calendar
import pandas as pd
from datetime import datetime, timedelta
from parser import parse_syllabus
from canvas_ics import parse_canvas_ics
from scorer import score_deadlines
from visualizer import (
    create_calendar_heatmap, create_single_month_heatmap,
    get_month_day_details, create_summary_cards
)

st.set_page_config(page_title="Termly", page_icon="📅", layout="wide")

st.title("📅 Termly")
st.subheader("See your semester before it hits you.")
st.markdown("---")

# ── Sidebar ───────────────────────────────────────────────────────
st.sidebar.header("⚙️ Semester Settings")
semester_start = st.sidebar.date_input("Semester Start Date", value=None)
num_weeks = st.sidebar.slider("Semester Length (weeks)", 12, 18, 16)

# ── Step 1: Canvas URL ────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.markdown("### 🗓️ Step 1 — Canvas Calendar")
st.sidebar.markdown("Paste your Canvas calendar URL. This is the **only source** Termly uses for assignment dates.")

with st.sidebar.expander("📋 How to get your Canvas calendar URL"):
    st.markdown("""
1. Go to **canvas.wisc.edu**
2. Click **Account** (top-left avatar) → **Settings**
3. Scroll to **Other Options**
4. Click **Calendar Feed**
5. Copy the URL — looks like:
   `https://canvas.wisc.edu/feeds/calendars/user_xxx.ics`
6. Paste below ↓

> ✅ Paste once — Termly stays synced automatically every time you generate.
""")

canvas_url = st.sidebar.text_input(
    "Canvas calendar feed URL",
    placeholder="https://canvas.wisc.edu/feeds/calendars/user_xxx.ics"
)

# ── Step 2: Syllabi for weights + AI suggestions ──────────────────
st.sidebar.markdown("---")
st.sidebar.markdown("### 📚 Step 2 — Syllabi (for weights + study tips)")
st.sidebar.markdown("Upload syllabi so Termly knows grade weights and can generate weekly study suggestions. **Does not affect dates.**")

num_courses = st.sidebar.number_input("How many courses?", min_value=1, max_value=8, value=3)

uploaded_courses = []
for i in range(num_courses):
    st.sidebar.markdown(f"**Course {i+1}**")
    course_name = st.sidebar.text_input(
        "Course name (match Canvas exactly)",
        key=f"name_{i}",
        placeholder="e.g. COMPSCI320"
    )
    uploaded_files = st.sidebar.file_uploader(
        "Syllabus files (PDF, HTML, MHTML)",
        type=["pdf", "html", "htm", "mhtml", "mht"],
        key=f"pdf_{i}",
        accept_multiple_files=True
    )
    if course_name and uploaded_files:
        uploaded_courses.append({'name': course_name, 'files': uploaded_files})

# ── Step 3: Manual fallback ───────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.markdown("### ✏️ Step 3 — Manual Entry (fallback only)")
st.sidebar.markdown("For anything Canvas missed.")

with st.sidebar.expander("Add manual deadlines"):
    manual_course = st.text_input("Course", key="mc", placeholder="e.g. ANSCI 320")
    manual_date = st.date_input("Date", key="md", value=None)
    manual_type = st.selectbox("Type", ["exam", "midterm", "final exam", "quiz", "project", "paper", "assignment", "lab", "homework"], key="mt")
    manual_weight = st.slider("Weight (%)", 1, 40, 10, key="mw")
    manual_desc = st.text_input("Description", key="mdesc", placeholder="e.g. Midterm 1")

    if st.button("➕ Add"):
        if manual_course and manual_date and manual_desc:
            if 'manual_deadlines' not in st.session_state:
                st.session_state.manual_deadlines = []
            st.session_state.manual_deadlines.append({
                'course': manual_course,
                'date': datetime.combine(manual_date, datetime.min.time()),
                'description': manual_desc,
                'type': manual_type,
                'weight': manual_weight
            })
            st.success(f"Added: {manual_desc}")

    if st.session_state.get('manual_deadlines'):
        st.markdown(f"**{len(st.session_state.manual_deadlines)} manual deadline(s)**")
        if st.button("🗑️ Clear all"):
            st.session_state.manual_deadlines = []

# ── Generate ──────────────────────────────────────────────────────
if st.button("🚀 Generate My Semester Forecast", use_container_width=True):
    if not semester_start:
        st.error("Please set a semester start date.")
    elif not canvas_url and not st.session_state.get('manual_deadlines'):
        st.error("Please paste your Canvas calendar URL.")
    else:
        all_deadlines = []
        syllabus_data = {}  # course_name → {weights, topics} — used only for AI suggestions

        # ── CANVAS: primary source for ALL dates ──────────────────
        if canvas_url.strip():
            try:
                with st.spinner("📡 Fetching Canvas calendar..."):
                    all_deadlines = parse_canvas_ics(
                        canvas_url.strip(),
                        course_names=None,  # take everything, no filtering
                        default_year=semester_start.year
                    )
                st.success(f"✅ {len(all_deadlines)} deadlines fetched from Canvas")
            except Exception as e:
                st.error(f"❌ Canvas fetch failed: {e}")
                st.stop()

        # ── SYLLABI: extract weights + topics only ─────────────────
        # Weights get applied to matching Canvas deadlines
        # Topics get stored for AI suggestions later
        if uploaded_courses:
            with st.spinner("📖 Reading syllabi for weights and topics..."):
                for course in uploaded_courses:
                    tmp_paths = []
                    for f in course['files']:
                        name = f.name.lower()
                        if name.endswith(('.mhtml', '.mht')): suffix = '.mhtml'
                        elif name.endswith(('.html', '.htm')): suffix = '.html'
                        else: suffix = '.pdf'
                        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                            tmp.write(f.read())
                            tmp_paths.append(tmp.name)

                    syllabus_items = parse_syllabus(tmp_paths, course['name'])
                    syllabus_data[course['name']] = syllabus_items

                    for p in tmp_paths:
                        os.unlink(p)

            # Apply syllabus weights to Canvas deadlines
            # Match by course name (fuzzy) + assignment type
            # NEVER touch the date — Canvas date is always kept
            import re as _re

            def _course_match(a, b):
                a = _re.sub(r'\s+', '', a).lower()
                b = _re.sub(r'\s+', '', b).lower()
                return a in b or b in a

            def _type_match(a, b):
                return a.lower() == b.lower()

            for d in all_deadlines:
                for course_name, items in syllabus_data.items():
                    if not _course_match(d['course'], course_name):
                        continue
                    for item in items:
                        if _type_match(d['type'], item['type']):
                            d['weight'] = item['weight']
                            break

            st.success(f"✅ Syllabus weights applied to {sum(len(v) for v in syllabus_data.values())} items")

        # ── MANUAL: add on top ─────────────────────────────────────
        if st.session_state.get('manual_deadlines'):
            all_deadlines.extend(st.session_state.manual_deadlines)
            st.info(f"➕ {len(st.session_state.manual_deadlines)} manual deadline(s) added")

        if not all_deadlines:
            st.warning("No deadlines found.")
        else:
            with st.spinner("📊 Calculating semester load..."):
                s_str = semester_start.strftime('%Y-%m-%d')
                df = score_deadlines(all_deadlines, s_str, num_weeks)

            st.session_state.update({
                'df': df,
                'semester_start_str': s_str,
                'num_weeks': num_weeks,
                'syllabus_data': syllabus_data,
                'all_deadlines': all_deadlines,
            })

# ── Display ───────────────────────────────────────────────────────
if 'df' in st.session_state:
    df = st.session_state['df']
    s_str = st.session_state['semester_start_str']
    nw = st.session_state['num_weeks']

    # Summary cards
    st.markdown("## 📊 Semester Overview")
    summary = create_summary_cards(df)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Deadlines", summary['total_deadlines'])
    c2.metric("Crunch Weeks 🔴", summary['high_stress_weeks'])
    c3.metric("Peak Week", summary['peak_week'].split('(')[0].strip())
    c4.metric("Free Weeks 🟢", summary['free_weeks'])

    # Verification table
    with st.expander("🔍 Verify all loaded deadlines"):
        all_rows = []
        for _, row in df.iterrows():
            for d in row['deadlines']:
                all_rows.append({
                    'Date': d['date'],
                    'Course': d['course'],
                    'Type': d['type'].capitalize(),
                    'Description': d['description'],
                    'Weight': f"{d['weight']}%",
                })
        if all_rows:
            vdf = pd.DataFrame(all_rows).sort_values('Date').reset_index(drop=True)
            st.dataframe(vdf, use_container_width=True, height=400)

    st.markdown("---")

    # Calendar
    st.markdown("## 📅 Semester Calendar")
    vcol1, vcol2 = st.columns([3, 1])
    with vcol2:
        view_mode = st.radio("View", ["Full Semester", "Single Month"], horizontal=True)

    if view_mode == "Full Semester":
        fig = create_calendar_heatmap(df, s_str, nw)
        st.plotly_chart(fig, use_container_width=True)
    else:
        s_date = datetime.strptime(s_str, '%Y-%m-%d').date()
        e_date = s_date + timedelta(weeks=nw)
        months = []
        cur = s_date.replace(day=1)
        while cur <= e_date.replace(day=1):
            months.append((cur.year, cur.month))
            cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)

        month_labels = [f"{calendar.month_name[m]} {y}" for y, m in months]
        selected = st.select_slider("Select month", options=month_labels)
        yr, mo = months[month_labels.index(selected)]

        fig = create_single_month_heatmap(df, s_str, nw, yr, mo)
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("### 📋 Day Details — expand any day")
        details = get_month_day_details(df, s_str, nw, yr, mo)
        for week in calendar.monthcalendar(yr, mo):
            cols = st.columns(7)
            for col_i, day in enumerate(week):
                if day == 0 or day not in details:
                    cols[col_i].markdown(
                        f"<div style='opacity:0.2;text-align:center'>{day if day else ''}</div>",
                        unsafe_allow_html=True
                    )
                    continue
                info = details[day]
                emoji = "🔴" if info['type'] == 'deadline' else "🟡" if info['type'] == 'prep' else "🟢"
                with cols[col_i]:
                    with st.expander(f"{emoji} {day}"):
                        for item in info['items']:
                            st.markdown(item)

    st.markdown("---")

    # Deadline breakdown
    st.markdown("## 📋 Full Deadline Breakdown")
    high = df[df['stress_level'] == 'High']
    if len(high) > 0:
        st.error(f"🚨 {len(high)} crunch week(s) detected.")
        for _, row in high.iterrows():
            with st.expander(f"🔴 {row['week_label']} — Score: {row['normalized_score']:.0f}/100"):
                for d in row['deadlines']:
                    st.markdown(f"- **{d['course']}** | {d['type'].capitalize()} | {d['date']} | Weight: {d['weight']}%")

    st.markdown("### All Weeks")
    for _, row in df.iterrows():
        if row['deadline_count'] > 0:
            lbl = "🔴" if row['stress_level'] == 'High' else "🟡" if row['stress_level'] == 'Medium' else "🟢"
            with st.expander(f"{lbl} {row['week_label']} — {row['deadline_count']} deadline(s)"):
                for d in row['deadlines']:
                    st.markdown(f"- **{d['course']}** | {d['type'].capitalize()} | {d['date']} | Weight: {d['weight']}%")

st.markdown("---")
st.markdown("<center>Built for UW–Madison students · Termly v0.1</center>", unsafe_allow_html=True)