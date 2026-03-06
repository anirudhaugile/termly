import pandas as pd
from datetime import datetime, timedelta

def get_week_number(date, semester_start):
    """Calculate which week of the semester a date falls in."""
    delta = date - semester_start
    week = (delta.days // 7) + 1
    return week

def calculate_weight_multiplier(assignment_type):
    """Assign a base multiplier based on assignment type."""
    multipliers = {
        'final': 3.0,
        'midterm': 2.5,
        'exam': 2.5,
        'test': 2.0,
        'project': 1.8,
        'paper': 1.5,
        'essay': 1.5,
        'presentation': 1.5,
        'quiz': 1.0,
        'homework': 0.8,
        'hw': 0.8,
        'assignment': 0.8,
        'lab': 0.7,
        'due': 1.0
    }
    return multipliers.get(assignment_type.lower(), 1.0)

def score_deadlines(deadlines, semester_start, num_weeks=16):
    """
    Takes a list of deadline dicts, returns a week-by-week stress score.
    
    Scoring logic:
    - Each deadline contributes: weight% × type_multiplier
    - Multiple deadlines in same week stack (with a clustering bonus)
    - Output: DataFrame with week number, score, and deadline list
    """
    if not deadlines:
        return pd.DataFrame()

    semester_start = datetime.strptime(semester_start, '%Y-%m-%d')

    # Initialize weeks
    weeks = {i: {'score': 0, 'deadlines': []} for i in range(1, num_weeks + 1)}

    for item in deadlines:
        date = item['date']
        week = get_week_number(date, semester_start)

        # Skip if outside semester range
        if week < 1 or week > num_weeks:
            continue

        # Calculate this deadline's stress contribution
        type_multiplier = calculate_weight_multiplier(item['type'])
        base_score = (item['weight'] / 100) * type_multiplier * 100

        weeks[week]['score'] += base_score
        weeks[week]['deadlines'].append({
            'course': item['course'],
            'description': item['description'],
            'type': item['type'],
            'weight': item['weight'],
            'date': item['date'].strftime('%b %d')
        })

    # Apply clustering multiplier — weeks with 3+ deadlines get a penalty
    for week_num, data in weeks.items():
        count = len(data['deadlines'])
        if count >= 3:
            data['score'] *= 1.4  # 40% penalty for pile-ups
        elif count == 2:
            data['score'] *= 1.15  # 15% penalty for pairs

    # Build DataFrame
    rows = []
    for week_num in range(1, num_weeks + 1):
        week_start = semester_start + timedelta(weeks=week_num - 1)
        rows.append({
            'week': week_num,
            'week_label': f"Week {week_num} ({week_start.strftime('%b %d')})",
            'week_start': week_start,
            'score': round(weeks[week_num]['score'], 2),
            'deadline_count': len(weeks[week_num]['deadlines']),
            'deadlines': weeks[week_num]['deadlines']
        })

    df = pd.DataFrame(rows)

    # Normalize scores to 0–100 scale
    max_score = df['score'].max()
    if max_score > 0:
        df['normalized_score'] = (df['score'] / max_score * 100).round(2)
    else:
        df['normalized_score'] = 0

    # Assign stress level labels
    def label_stress(score):
        if score >= 75:
            return 'High'
        elif score >= 40:
            return 'Medium'
        else:
            return 'Low'

    df['stress_level'] = df['normalized_score'].apply(label_stress)

    return df

'''
What this does in plain English:

Takes all the deadlines the parser found and spreads them across a 16-week semester
Each deadline gets a stress score based on two things: its percentage weight (a 30% exam hits harder) and its type (finals hit hardest, homework least)
If 3+ things pile up in the same week, it adds a 40% crunch penalty — that's the clustering logic, the core insight of Termly
Normalizes everything to a 0 to 100 scale so the heatmap makes sense
Labels each week as Low / Medium / High stress

'''