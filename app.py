import streamlit as st
import tempfile
import os
from parser import parse_syllabus
from scorer import score_deadlines
from visualizer import create_heatmap, create_summary_cards

# --- Page Config ---
st.set_page_config(
    page_title="Termly",
    page_icon="📅",
    layout="wide"
)

# --- Header ---
st.title("📅 Termly")
st.subheader("See your semester before it hits you.")
st.markdown("---")

# --- Sidebar: Semester Settings ---
st.sidebar.header("⚙️ Semester Settings")
semester_start = st.sidebar.date_input(
    "Semester Start Date",
    value=None,
    help="Enter the first day of your semester"
)
num_weeks = st.sidebar.slider("Semester Length (weeks)", 12, 18, 16)

st.sidebar.markdown("---")
st.sidebar.markdown("### 📚 Upload Your Syllabi")
st.sidebar.markdown("Upload one PDF per course. Termly will extract deadlines automatically.")

# --- Course Upload Section ---
num_courses = st.sidebar.number_input("How many courses?", min_value=1, max_value=8, value=3)

uploaded_courses = []
for i in range(num_courses):
    st.sidebar.markdown(f"**Course {i+1}**")
    course_name = st.sidebar.text_input(f"Course name", key=f"name_{i}", placeholder=f"e.g. CS 301")
    uploaded_file = st.sidebar.file_uploader(f"Upload syllabus PDF", type="pdf", key=f"pdf_{i}")

    if course_name and uploaded_file:
        uploaded_courses.append({
            'name': course_name,
            'file': uploaded_file
        })

# --- Main: Run Analysis ---
if st.button("🚀 Generate My Semester Forecast", use_container_width=True):

    if not semester_start:
        st.error("Please set your semester start date in the sidebar.")
    elif len(uploaded_courses) == 0:
        st.error("Please upload at least one syllabus with a course name.")
    else:
        all_deadlines = []

        with st.spinner("Reading your syllabi..."):
            for course in uploaded_courses:
                # Save uploaded file to temp location
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(course['file'].read())
                    tmp_path = tmp.name

                # Parse the syllabus
                deadlines = parse_syllabus(tmp_path, course['name'])
                all_deadlines.extend(deadlines)

                # Clean up temp file
                os.unlink(tmp_path)

        if len(all_deadlines) == 0:
            st.warning("No deadlines were found in your syllabi. Your PDFs may be scanned images or have unusual formatting. Try adding deadlines manually below.")
        else:
            # Score the deadlines
            with st.spinner("Calculating your semester load..."):
                semester_start_str = semester_start.strftime('%Y-%m-%d')
                df = score_deadlines(all_deadlines, semester_start_str, num_weeks)

            # --- Summary Cards ---
            st.markdown("## 📊 Semester Overview")
            summary = create_summary_cards(df)

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Deadlines", summary['total_deadlines'])
            col2.metric("Crunch Weeks 🔴", summary['high_stress_weeks'])
            col3.metric("Peak Week", summary['peak_week'].split('(')[0].strip())
            col4.metric("Free Weeks 🟢", summary['free_weeks'])

            st.markdown("---")

            # --- Heatmap ---
            st.markdown("## 📅 Weekly Load Forecast")
            fig = create_heatmap(df)
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("---")

            # --- Deadline Breakdown ---
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

# --- Footer ---
st.markdown("---")
st.markdown("<center>Built for UW–Madison students · Termly v0.1</center>", unsafe_allow_html=True)


