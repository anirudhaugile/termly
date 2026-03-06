import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import datetime, timedelta
import calendar

# Force calendar to start on Sunday
calendar.setfirstweekday(6)
DAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

def get_day_scores(df):
    """Convert week-based scores to day-level scores."""
    day_scores = {}

    for _, row in df.iterrows():
        week_start = row['week_start']
        for d in row['deadlines']:
            try:
                date_obj = datetime.strptime(f"{d['date']} 2026", "%b %d %Y").date()
            except:
                date_obj = week_start.date()

            key = date_obj
            if key not in day_scores:
                day_scores[key] = {'score': 0, 'deadlines': []}

            day_scores[key]['score'] += (row['normalized_score'] / max(len(row['deadlines']), 1))
            day_scores[key]['deadlines'].append(d)

    if day_scores:
        max_score = max(v['score'] for v in day_scores.values())
        if max_score > 0:
            for key in day_scores:
                day_scores[key]['score'] = min((day_scores[key]['score'] / max_score) * 100, 100)

    return day_scores


def get_prep_days(day_scores, lookahead=4):
    """
    For each deadline day, mark the N days before it as prep days.
    Prep score = deadline score * decay (closer = higher).
    """
    prep_days = {}
    for deadline_date, info in day_scores.items():
        score = info['score']
        for i in range(1, lookahead + 1):
            prep_date = deadline_date - timedelta(days=i)
            decay = (lookahead - i + 1) / lookahead  # 1.0 → 0.25
            prep_score = score * decay * 0.35  # max 35% of deadline score
            label = f"📖 Prep: {', '.join(set(d['course'] for d in info['deadlines']))}"

            if prep_date not in day_scores:  # don't overwrite real deadline days
                if prep_date not in prep_days:
                    prep_days[prep_date] = {'score': 0, 'label': label}
                prep_days[prep_date]['score'] = max(prep_days[prep_date]['score'], prep_score)
                prep_days[prep_date]['label'] = label

    return prep_days


def create_calendar_heatmap(df, semester_start_str, num_weeks, view_mode='full'):
    """
    Build monthly calendar heatmap.
    view_mode: 'full' = all months, 'single' = one month at a time (handled by app.py)
    """
    day_scores = get_day_scores(df)
    prep_days = get_prep_days(day_scores)

    semester_start = datetime.strptime(semester_start_str, '%Y-%m-%d').date()
    semester_end = semester_start + timedelta(weeks=num_weeks)

    # Collect months
    months = []
    current = semester_start.replace(day=1)
    while current <= semester_end.replace(day=1):
        months.append((current.year, current.month))
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)

    return _build_figure(months, day_scores, prep_days, semester_start, semester_end)


def create_single_month_heatmap(df, semester_start_str, num_weeks, year, month):
    day_scores = get_day_scores(df)
    prep_days = get_prep_days(day_scores)
    semester_start = datetime.strptime(semester_start_str, '%Y-%m-%d').date()
    semester_end = semester_start + timedelta(weeks=num_weeks)
    return _build_figure([(year, month)], day_scores, prep_days, semester_start, semester_end, single=True)


def _build_figure(months, day_scores, prep_days, semester_start, semester_end, single=False):
    n_months = len(months)
    if single:
        rows, cols = 1, 1
    else:
        cols = 2
        rows = (n_months + 1) // cols

    subplot_titles = [
        f"{calendar.month_name[m]} {y}" for y, m in months
    ]

    fig = make_subplots(
        rows=rows, cols=cols,
        subplot_titles=subplot_titles,
        vertical_spacing=0.06,
        horizontal_spacing=0.04
    )

    for idx, (year, month) in enumerate(months):
        row = idx // cols + 1
        col = idx % cols + 1

        # calendar.monthcalendar respects setfirstweekday (Sunday)
        cal = calendar.monthcalendar(year, month)

        z_vals, text_vals, hover_vals = [], [], []

        for week in cal:
            z_row, text_row, hover_row = [], [], []
            for day in week:
                if day == 0:
                    z_row.append(None)
                    text_row.append('')
                    hover_row.append('')
                else:
                    date = datetime(year, month, day).date()
                    in_semester = semester_start <= date <= semester_end

                    if not in_semester:
                        z_row.append(None)
                        text_row.append(str(day))
                        hover_row.append('')
                    elif date in day_scores:
                        info = day_scores[date]
                        score = info['score']
                        hover = f"<b>{date.strftime('%b %d')}</b><br>"
                        for d in info['deadlines']:
                            hover += f"📌 {d['course']} — {d['type'].capitalize()}<br>"
                        z_row.append(max(score, 15))  # floor so it shows color
                        text_row.append(str(day))
                        hover_row.append(hover)
                    elif date in prep_days:
                        info = prep_days[date]
                        score = info['score']
                        hover = f"<b>{date.strftime('%b %d')}</b><br>{info['label']}"
                        z_row.append(max(score, 5))
                        text_row.append(str(day))
                        hover_row.append(hover)
                    else:
                        z_row.append(3)  # very faint green for free days
                        text_row.append(str(day))
                        hover_row.append(f"<b>{date.strftime('%b %d')}</b><br>✅ Nothing due")

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
                textfont=dict(size=11),
                xgap=4,
                ygap=4,
                colorscale=[
                    [0.00, '#0d1f0d'],   # near-black green (free days)
                    [0.05, '#1a4d1a'],   # very dark green
                    [0.15, '#2ecc71'],   # green (prep days)
                    [0.40, '#f1c40f'],   # yellow
                    [0.65, '#f39c12'],   # orange
                    [1.00, '#e74c3c'],   # red (crunch)
                ],
                showscale=(idx == 0),
                colorbar=dict(
                    title=dict(text='Stress', side='right'),
                    tickvals=[3, 15, 40, 65, 100],
                    ticktext=['Free', 'Prep', 'Low', 'Med', 'High'],
                    len=0.35,
                    y=1.0,
                    yanchor='top',
                    thickness=15,
                ) if idx == 0 else {},
                zmin=0,
                zmax=100,
            ),
            row=row, col=col
        )

        fig.update_xaxes(
            tickvals=list(range(7)),
            ticktext=DAY_LABELS,
            row=row, col=col,
            tickfont=dict(size=10),
            side='top'
        )
        fig.update_yaxes(
            showticklabels=False,
            autorange='reversed',  # top to bottom = first week → last week
            row=row, col=col
        )

    height = 280 * rows if not single else 320
    fig.update_layout(
        title=dict(
            text='📅 Termly — Semester Calendar Heatmap',
            font=dict(size=20)
        ),
        paper_bgcolor='#0e1117',
        plot_bgcolor='#0e1117',
        font_color='white',
        height=height,
        margin=dict(t=80, b=20, l=10, r=10)
    )

    return fig


def create_summary_cards(df):
    high_weeks = df[df['stress_level'] == 'High']
    peak_week = df.loc[df['normalized_score'].idxmax()]
    total_deadlines = df['deadline_count'].sum()
    free_weeks = df[df['deadline_count'] == 0]

    return {
        'total_deadlines': int(total_deadlines),
        'high_stress_weeks': len(high_weeks),
        'peak_week': peak_week['week_label'],
        'peak_score': round(peak_week['normalized_score'], 1),
        'free_weeks': len(free_weeks)
    }