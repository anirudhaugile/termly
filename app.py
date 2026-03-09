import streamlit as st
import tempfile
import os
import calendar
from datetime import datetime, timedelta
from parser import parse_syllabus
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

st.sidebar.markdown("---")
st.sidebar.markdown("### 📚 Upload Your Syllabi")
st.sidebar.markdown("Upload PDF or HTML syllabi. For Canvas-only courses, use manual entry.")

num_courses = st.sidebar.number_input("How many courses?", min_value=1, max_value=8, value=3)

uploaded_courses = []
for i in range(num_courses):
    st.sidebar.markdown(f"**Course {i+1}**")
    course_name = st.sidebar.text_input("Course name", key=f"name_{i}", placeholder="e.g. CS 320")
    uploaded_file = st.sidebar.file_uploader(
        "Upload syllabus (PDF, HTML, or MHTML)",
        type=["pdf", "html", "htm", "mhtml", "mht"],
        key=f"pdf_{i}"
    )
    if course_name and uploaded_file:
        uploaded_courses.append({'name': course_name, 'file': uploaded_file})

# ── Manual Entry ──────────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.markdown("### ✏️ Manual Deadline Entry")

with st.sidebar.expander("Add manual deadlines"):
    manual_course = st.text_input("Course name", key="mc", placeholder="e.g. LIS 440")
    manual_date = st.date_input("Deadline date", key="md", value=None)
    manual_type = st.selectbox("Type", ["exam","midterm","final exam","quiz","project","paper","assignment","lab","due"], key="mt")
    manual_weight = st.slider("Weight (%)", 5, 40, 10, key="mw")
    manual_desc = st.text_input("Description", key="mdesc", placeholder="e.g. Midterm 1")

    if st.button("➕ Add Deadline"):
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
        if st.button("🗑️ Clear all manual"):
            st.session_state.manual_deadlines = []

# ── Generate ──────────────────────────────────────────────────────
if st.button("🚀 Generate My Semester Forecast", use_container_width=True):
    if not semester_start:
        st.error("Please set your semester start date.")
    elif not uploaded_courses and not st.session_state.get('manual_deadlines'):
        st.error("Please upload at least one syllabus or add manual deadlines.")
    else:
        all_deadlines = []
        if uploaded_courses:
            with st.spinner("Reading your syllabi..."):
                for course in uploaded_courses:
                    name = course['file'].name.lower()
                    if name.endswith(('.mhtml', '.mht')): suffix = '.mhtml'
                    elif name.endswith(('.html', '.htm')): suffix = '.html'
                    else: suffix = '.pdf'
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(course['file'].read())
                        tmp_path = tmp.name
                    all_deadlines.extend(parse_syllabus(tmp_path, course['name']))
                    os.unlink(tmp_path)

        if st.session_state.get('manual_deadlines'):
            all_deadlines.extend(st.session_state.manual_deadlines)

        if not all_deadlines:
            st.warning("No deadlines found. Try manual entry.")
        else:
            with st.spinner("Calculating your semester load..."):
                s_str = semester_start.strftime('%Y-%m-%d')
                df = score_deadlines(all_deadlines, s_str, num_weeks)
            st.session_state.update({'df': df, 'semester_start_str': s_str, 'num_weeks': num_weeks})

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

    st.markdown("---")
    st.markdown("## 📅 Semester Calendar")

    vcol1, vcol2 = st.columns([3, 1])
    with vcol2:
        view_mode = st.radio("View", ["Full Semester", "Single Month"], horizontal=True)

    if view_mode == "Full Semester":
        fig = create_calendar_heatmap(df, s_str, nw)
        st.plotly_chart(fig, use_container_width=True)

    else:
        # Build month list
        s_date = datetime.strptime(s_str, '%Y-%m-%d').date()
        e_date = s_date + timedelta(weeks=nw)
        months = []
        cur = s_date.replace(day=1)
        while cur <= e_date.replace(day=1):
            months.append((cur.year, cur.month))
            cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)

        month_labels = [f"{calendar.month_name[m]} {y}" for y, m in months]
        selected = st.select_slider("Select month", options=month_labels)
        sel_idx = month_labels.index(selected)
        yr, mo = months[sel_idx]

        fig = create_single_month_heatmap(df, s_str, nw, yr, mo)
        st.plotly_chart(fig, use_container_width=True)

        # ── Expandable day detail ─────────────────────
        st.markdown("### 📋 Day Details — click a day to expand")
        details = get_month_day_details(df, s_str, nw, yr, mo)

        cal_weeks = calendar.monthcalendar(yr, mo)
        for week in cal_weeks:
            cols = st.columns(7)
            for col_i, day in enumerate(week):
                if day == 0 or day not in details:
                    cols[col_i].markdown(f"<div style='opacity:0.2;text-align:center'>{day if day else ''}</div>", unsafe_allow_html=True)
                    continue
                info = details[day]
                if info['type'] == 'deadline':
                    emoji = "🔴"
                elif info['type'] == 'prep':
                    emoji = "🟡"
                else:
                    emoji = "🟢"
                with cols[col_i]:
                    with st.expander(f"{emoji} {day}"):
                        for item in info['items']:
                            st.markdown(item)

    st.markdown("---")

    # ── Deadline Breakdown ────────────────────────────
    st.markdown("## 📋 Full Deadline Breakdown")
    high = df[df['stress_level'] == 'High']
    if len(high) > 0:
        st.error(f"🚨 You have {len(high)} crunch week(s).")
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