import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import calendar

calendar.setfirstweekday(6)  # Sunday first
DAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']


def get_day_scores(df):
    day_scores = {}
    for _, row in df.iterrows():
        week_start = row['week_start']
        for d in row['deadlines']:
            try:
                date_obj = datetime.strptime(f"{d['date']} 2026", "%b %d %Y").date()
            except:
                date_obj = week_start.date()
            if date_obj not in day_scores:
                day_scores[date_obj] = {'score': 0, 'deadlines': []}
            day_scores[date_obj]['score'] += row['normalized_score'] / max(len(row['deadlines']), 1)
            day_scores[date_obj]['deadlines'].append(d)

    if day_scores:
        mx = max(v['score'] for v in day_scores.values())
        if mx > 0:
            for k in day_scores:
                day_scores[k]['score'] = min(day_scores[k]['score'] / mx * 100, 100)
    return day_scores


def get_prep_days(day_scores, lookahead=4):
    prep_days = {}
    for deadline_date, info in day_scores.items():
        score = info['score']
        courses = set(d['course'] for d in info['deadlines'])
        for i in range(1, lookahead + 1):
            prep_date = deadline_date - timedelta(days=i)
            if prep_date not in day_scores:
                # Intensity increases as deadline approaches: day before = strongest
                intensity = i / lookahead  # further away = higher i = lighter
                prep_score = score * (1 - intensity) * 0.4  # max ~40% of deadline score
                label = f"📖 Prep: {', '.join(courses)}"
                if prep_date not in prep_days or prep_days[prep_date]['score'] < prep_score:
                    prep_days[prep_date] = {'score': prep_score, 'label': label, 'courses': courses}
    return prep_days


def _build_figure(months, day_scores, prep_days, semester_start, semester_end, single=False):
    n = len(months)
    cols = 1 if single else 2
    rows = (n + cols - 1) // cols

    subplot_titles = [f"{calendar.month_name[m]} {y}" for y, m in months]

    fig = make_subplots(
        rows=rows, cols=cols,
        subplot_titles=subplot_titles,
        vertical_spacing=0.06,
        horizontal_spacing=0.04
    )

    for idx, (year, month) in enumerate(months):
        r = idx // cols + 1
        c = idx % cols + 1
        cal = calendar.monthcalendar(year, month)

        z_vals, text_vals, hover_vals = [], [], []

        for week in cal:
            z_row, text_row, hover_row = [], [], []
            for day in week:
                if day == 0:
                    z_row.append(None); text_row.append(''); hover_row.append('')
                    continue
                date = datetime(year, month, day).date()
                in_sem = semester_start <= date <= semester_end

                if not in_sem:
                    z_row.append(None); text_row.append(str(day)); hover_row.append('')
                elif date in day_scores:
                    info = day_scores[date]
                    score = info['score']
                    hover = f"<b>{date.strftime('%b %d')}</b><br>"
                    for d in info['deadlines']:
                        hover += f"📌 {d['course']} — {d['type'].capitalize()}<br>"
                    z_row.append(max(score, 60))  # deadline days: floor at 60 (yellow+)
                    text_row.append(str(day))
                    hover_row.append(hover)
                elif date in prep_days:
                    info = prep_days[date]
                    score = info['score']
                    hover = f"<b>{date.strftime('%b %d')}</b><br>{info['label']}"
                    # prep days: 15-45 range (light green → yellow-green)
                    z_row.append(max(min(score, 45), 15))
                    text_row.append(str(day))
                    hover_row.append(hover)
                else:
                    z_row.append(5)  # free days: near zero = dark green
                    text_row.append(str(day))
                    hover_row.append(f"<b>{date.strftime('%b %d')}</b><br>✅ Free day")

            z_vals.append(z_row)
            text_vals.append(text_row)
            hover_vals.append(hover_row)

        fig.add_trace(
            go.Heatmap(
                z=z_vals,
                text=text_vals,
                hovertext=hover_vals,
                hoverinfo='text',
                texttemplate='%{text}',
                textfont=dict(size=11, color='white'),
                xgap=4, ygap=4,
                colorscale=[
                    [0.00, '#0a1f0a'],   # 0-5: very dark green — free days
                    [0.08, '#1a5c1a'],   # light green — distant prep
                    [0.20, '#27ae60'],   # medium green — closer prep
                    [0.45, '#f1c40f'],   # yellow — prep day 1 before deadline
                    [0.62, '#e67e22'],   # orange — light deadline
                    [0.80, '#e74c3c'],   # red — heavy deadline
                    [1.00, '#c0392b'],   # dark red — peak crunch
                ],
                showscale=(idx == 0),
                colorbar=dict(
                    title=dict(text='Load', side='right'),
                    tickvals=[5, 20, 45, 62, 85, 100],
                    ticktext=['Free', 'Prep', 'Soon', 'Due', 'Heavy', 'Peak'],
                    len=0.4, y=1.0, yanchor='top', thickness=14,
                ) if idx == 0 else {},
                zmin=0, zmax=100,
            ),
            row=r, col=c
        )

        fig.update_xaxes(
            tickvals=list(range(7)), ticktext=DAY_LABELS,
            row=r, col=c, tickfont=dict(size=10), side='top'
        )
        fig.update_yaxes(
            showticklabels=False, autorange='reversed',
            row=r, col=c
        )

    fig.update_layout(
        title=dict(text='📅 Termly — Semester Calendar Heatmap', font=dict(size=20)),
        paper_bgcolor='#0e1117', plot_bgcolor='#0e1117', font_color='white',
        height=300 * rows if not single else 340,
        margin=dict(t=80, b=20, l=10, r=10)
    )
    return fig


def create_calendar_heatmap(df, semester_start_str, num_weeks):
    day_scores = get_day_scores(df)
    prep_days = get_prep_days(day_scores)
    s = datetime.strptime(semester_start_str, '%Y-%m-%d').date()
    e = s + timedelta(weeks=num_weeks)
    months = _get_months(s, e)
    return _build_figure(months, day_scores, prep_days, s, e)


def create_single_month_heatmap(df, semester_start_str, num_weeks, year, month):
    day_scores = get_day_scores(df)
    prep_days = get_prep_days(day_scores)
    s = datetime.strptime(semester_start_str, '%Y-%m-%d').date()
    e = s + timedelta(weeks=num_weeks)
    return _build_figure([(year, month)], day_scores, prep_days, s, e, single=True)


def get_month_day_details(df, semester_start_str, num_weeks, year, month):
    """Returns per-day detail dict for the expandable day view in single month mode."""
    day_scores = get_day_scores(df)
    prep_days = get_prep_days(day_scores)
    s = datetime.strptime(semester_start_str, '%Y-%m-%d').date()
    e = s + timedelta(weeks=num_weeks)

    details = {}
    cal = calendar.monthcalendar(year, month)
    for week in cal:
        for day in week:
            if day == 0:
                continue
            date = datetime(year, month, day).date()
            if not (s <= date <= e):
                continue
            if date in day_scores:
                info = day_scores[date]
                details[day] = {
                    'type': 'deadline',
                    'score': info['score'],
                    'items': [f"📌 **{d['course']}** — {d['type'].capitalize()} (Weight: {d['weight']}%)" for d in info['deadlines']]
                }
            elif date in prep_days:
                info = prep_days[date]
                details[day] = {
                    'type': 'prep',
                    'score': info['score'],
                    'items': [f"📖 {info['label']}"]
                }
            else:
                details[day] = {'type': 'free', 'score': 0, 'items': ['✅ Free day']}
    return details


def _get_months(start, end):
    months = []
    cur = start.replace(day=1)
    while cur <= end.replace(day=1):
        months.append((cur.year, cur.month))
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    return months


def create_summary_cards(df):
    high_weeks = df[df['stress_level'] == 'High']
    peak_week = df.loc[df['normalized_score'].idxmax()]
    return {
        'total_deadlines': int(df['deadline_count'].sum()),
        'high_stress_weeks': len(high_weeks),
        'peak_week': peak_week['week_label'],
        'peak_score': round(peak_week['normalized_score'], 1),
        'free_weeks': len(df[df['deadline_count'] == 0])
    }