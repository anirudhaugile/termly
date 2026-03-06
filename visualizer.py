import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

def create_heatmap(df):
    """
    Takes the scored DataFrame and returns a Plotly heatmap figure.
    Color scale: green (low) → yellow (medium) → red (high)
    """

    # Color mapping
    color_map = {'Low': '#2ecc71', 'Medium': '#f39c12', 'High': '#e74c3c'}
    colors = df['stress_level'].map(color_map).tolist()

    # Build hover text — shows what's due that week
    hover_texts = []
    for _, row in df.iterrows():
        if row['deadline_count'] == 0:
            hover_texts.append(f"<b>{row['week_label']}</b><br>Nothing due — breathe.")
        else:
            text = f"<b>{row['week_label']}</b><br>Stress: {row['stress_level']} ({row['normalized_score']:.0f}/100)<br><br>"
            for d in row['deadlines']:
                text += f"📌 [{d['course']}] {d['type'].capitalize()} — {d['date']} ({d['weight']}%)<br>"
            hover_texts.append(text)

    # Bar chart styled as heatmap
    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=df['week_label'],
        y=df['normalized_score'],
        marker_color=colors,
        hovertext=hover_texts,
        hoverinfo='text',
        text=df['stress_level'],
        textposition='outside',
    ))

    # Danger zone line at 75
    fig.add_hline(
        y=75,
        line_dash='dash',
        line_color='red',
        annotation_text='Crunch Zone',
        annotation_position='top right'
    )

    fig.update_layout(
        title={
            'text': '📅 Termly — Your Semester Load Forecast',
            'font': {'size': 24}
        },
        xaxis_title='Week',
        yaxis_title='Stress Score (0–100)',
        xaxis_tickangle=-45,
        plot_bgcolor='#0e1117',
        paper_bgcolor='#0e1117',
        font_color='white',
        yaxis=dict(range=[0, 115]),
        showlegend=False,
        height=500,
        margin=dict(t=80, b=120)
    )

    return fig


def create_summary_cards(df):
    """
    Returns key stats for display above the heatmap.
    """
    high_weeks = df[df['stress_level'] == 'High']
    peak_week = df.loc[df['normalized_score'].idxmax()]
    total_deadlines = df['deadline_count'].sum()
    free_weeks = df[df['deadline_count'] == 0]

    summary = {
        'total_deadlines': int(total_deadlines),
        'high_stress_weeks': len(high_weeks),
        'peak_week': peak_week['week_label'],
        'peak_score': round(peak_week['normalized_score'], 1),
        'free_weeks': len(free_weeks)
    }

    return summary

'''
What this does in plain English:

Takes the scored data and builds a color-coded bar chart — green bars are light weeks, yellow is medium, red is crunch
Each bar is hoverable — hover over any week and it shows exactly what's due, for which course, and how much it's worth
Draws a red dashed "Crunch Zone" line at 75/100 so danger weeks are instantly obvious
Also generates summary stats — total deadlines, number of crunch weeks, your single worst week, and how many free weeks you have
'''