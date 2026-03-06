import streamlit as st
import tempfile
import os
from datetime import datetime, timedelta
import calendar
from parser import parse_syllabus
from scorer import score_deadlines
from visualizer import create_calendar_heatmap, create_single_month_heatmap, create_summary_cards

st.set_page_config(page_title="Termly", page_icon="📅", layout="wide")

st.title("📅 Termly")
st.subheader("See your semester before it hits you.")
st.markdown("---")

# ── Sidebar ──────────────────────────────────────────
st.sidebar.header("⚙️ Semester Settings")
semester_start = st.sidebar.date_input("Semester Start Date", value=None)
num_weeks = st.sidebar.slider("Semester Length (weeks)", 12, 18, 16)

st.sidebar.markdown("---")
st.sidebar.markdown("### 📚 Upload Your Syllabi")
st.sidebar.markdown("Upload PDF or HTML syllabi. For Canvas-only courses, use manual entry below.")

num_courses = st.sidebar.number_input("How many courses?", min_value=1, max_value=8, value=3)

uploaded_courses = []
for i in range(num_courses):
    st.sidebar.markdown(f"**Course {i+1}**")
    course_name = st.sidebar.text_input("Course name", key=f"name_{i}", placeholder="e.g. CS 320")
    uploaded_file = st.sidebar.file_uploader(
        "Upload syllabus (PDF or HTML)",
        type=["pdf", "html", "htm"],
        key=f"pdf_{i}"
    )
    if course_name and uploaded_file:
        uploaded_courses.append({'name': course_name, 'file': uploaded_file})

# ── Manual Entry ─────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.markdown("### ✏️ Manual Deadline Entry")

with st.sidebar.expander("Add manual deadlines"):
    manual_course = st.text_input("Course name", key="manual_course", placeholder="e.g. LIS 440")
    manual_date = st.date_input("Deadline date", key="manual_date", value=None)
    manual_type = st.selectbox("Type", ["exam", "midterm", "final exam", "quiz", "project", "paper", "assignment", "lab", "due"], key="manual_type")
    manual_weight = st.slider("Weight (%)", 5, 40, 10, key="manual_weight")
    manual_desc = st.text_input("Description", key="manual_desc", placeholder="e.g. Midterm 1")

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
        st.markdown(f"**{len(st.session_state.manual_deadlines)} manual deadline(s) added**")
        if st.button("🗑️ Clear all manual"):
            st.session_state.manual_deadlines = []

# ── Generate ─────────────────────────────────────────
if st.button("🚀 Generate My Semester Forecast", use_container_width=True):

    if not semester_start:
        st.error("Please set your semester start date.")
    elif len(uploaded_courses) == 0 and not st.session_state.get('manual_deadlines'):
        st.error("Please upload at least one syllabus or add manual deadlines.")
    else:
        all_deadlines = []

        if uploaded_courses:
            with st.spinner("Reading your syllabi..."):
                for course in uploaded_courses:
                    suffix = ".html" if course['file'].name.endswith(('.html', '.htm')) else ".pdf"
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(course['file'].read())
                        tmp_path = tmp.name
                    deadlines = parse_syllabus(tmp_path, course['name'])
                    all_deadlines.extend(deadlines)
                    os.unlink(tmp_path)

        if st.session_state.get('manual_deadlines'):
            all_deadlines.extend(st.session_state.manual_deadlines)

        if len(all_deadlines) == 0:
            st.warning("No deadlines found. Try manual entry.")
        else:
            with st.spinner("Calculating your semester load..."):
                semester_start_str = semester_start.strftime('%Y-%m-%d')
                df = score_deadlines(all_deadlines, semester_start_str, num_weeks)
            st.session_state['df'] = df
            st.session_state['semester_start_str'] = semester_start_str
            st.session_state['num_weeks'] = num_weeks

# ── Display results if available ─────────────────────
if 'df' in st.session_state:
    df = st.session_state['df']
    semester_start_str = st.session_state['semester_start_str']
    num_weeks = st.session_state['num_weeks']

    # Summary cards
    st.markdown("## 📊 Semester Overview")
    summary = create_summary_cards(df)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Deadlines", summary['total_deadlines'])
    col2.metric("Crunch Weeks 🔴", summary['high_stress_weeks'])
    col3.metric("Peak Week", summary['peak_week'].split('(')[0].strip())
    col4.metric("Free Weeks 🟢", summary['free_weeks'])

    st.markdown("---")

    # ── Calendar view toggle ──────────────────────────
    st.markdown("## 📅 Semester Calendar")

    view_col1, view_col2 = st.columns([3, 1])
    with view_col2:
        view_mode = st.radio("View", ["Full Semester", "Single Month"], horizontal=True)

    if view_mode == "Full Semester":
        fig = create_calendar_heatmap(df, semester_start_str, num_weeks)
        st.plotly_chart(fig, use_container_width=True)
    else:
        # Build month list
        s = datetime.strptime(semester_start_str, '%Y-%m-%d').date()
        e = s + timedelta(weeks=num_weeks)
        months = []
        cur = s.replace(day=1)
        while cur <= e.replace(day=1):
            months.append((cur.year, cur.month))
            cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)

        month_labels = [f"{calendar.month_name[m]} {y}" for y, m in months]
        selected_label = st.select_slider("Select month", options=month_labels)
        selected_idx = month_labels.index(selected_label)
        year, month = months[selected_idx]

        fig = create_single_month_heatmap(df, semester_start_str, num_weeks, year, month)
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # ── Deadline Breakdown ────────────────────────────
    st.markdown("## 📋 Full Deadline Breakdown")
    high_weeks = df[df['stress_level'] == 'High']

    if len(high_weeks) > 0:
        st.error(f"🚨 You have {len(high_weeks)} crunch week(s). Scroll down to see them.")
        for _, row in high_weeks.iterrows():
            with st.expander(f"🔴 {row['week_label']} — Score: {row['normalized_score']:.0f}/100"):
                for d in row['deadlines']:
                    st.markdown(f"- **{d['course']}** | {d['type'].capitalize()} | {d['date']} | Weight: {d['weight']}%")

    st.markdown("### All Weeks")
    for _, row in df.iterrows():
        if row['deadline_count'] > 0:
            label = "🔴" if row['stress_level'] == 'High' else "🟡" if row['stress_level'] == 'Medium' else "🟢"
            with st.expander(f"{label} {row['week_label']} — {row['deadline_count']} deadline(s)"):
                for d in row['deadlines']:
                    st.markdown(f"- **{d['course']}** | {d['type'].capitalize()} | {d['date']} | Weight: {d['weight']}%")

st.markdown("---")
st.markdown("<center>Built for UW–Madison students · Termly v0.1</center>", unsafe_allow_html=True)