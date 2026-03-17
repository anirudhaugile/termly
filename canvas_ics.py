"""
canvas_ics.py
Fetches and parses a Canvas calendar feed URL (.ics format).
Returns a list of deadline dicts compatible with Termly's scoring pipeline.

Canvas ICS events look like:
  SUMMARY: Assignment 1 [CS 320]
  DTSTART: 20260210T235900Z
  DESCRIPTION: Points: 100 | Course: CS 320
"""

import re
import ssl
import urllib.request
from datetime import datetime, timezone


# ─────────────────────────────────────────
# ICS Parser — no external dependencies
# ─────────────────────────────────────────
def fetch_ics(url):
    """Fetch raw ICS content from a URL."""
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={'User-Agent': 'Termly/1.0'})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
            return response.read().decode('utf-8', errors='ignore')
    except Exception as e:
        raise ConnectionError(f"Could not fetch Canvas calendar: {e}")


def parse_ics(ics_text):
    """
    Parse raw ICS text into a list of event dicts.
    Each event: {summary, dtstart, description, course}
    """
    events = []
    current = {}
    in_event = False

    for raw_line in ics_text.splitlines():
        line = raw_line.strip()

        if line == 'BEGIN:VEVENT':
            in_event = True
            current = {}
        elif line == 'END:VEVENT':
            if current:
                events.append(current)
            in_event = False
            current = {}
        elif in_event:
            if ':' in line:
                key, _, value = line.partition(':')
                key = key.split(';')[0].strip()  # strip params like DTSTART;TZID=...
                value = value.strip()
                current[key] = value

    return events


def parse_dt(dt_str):
    """
    Parse ICS datetime string to datetime object.
    Canvas stores times in UTC. We convert to US/Central (UW-Madison's timezone)
    since that's when assignments are actually due for the user.
    A quiz due 'Mar 17 at 11:59pm CT' is stored as 'Mar 18 04:59 UTC' — 
    without this fix it shows up as Mar 18 or Mar 19.
    """
    dt_str = dt_str.strip()

    # UTC datetime (ends with Z)
    if dt_str.endswith('Z'):
        try:
            dt_utc = datetime.strptime(dt_str, '%Y%m%dT%H%M%SZ')
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
            # Convert to Central Time (UTC-6 standard, UTC-5 daylight)
            # Spring semester is mostly CDT (UTC-5), starting mid-March
            # Use UTC-6 for Jan-Mar 7, UTC-5 for Mar 8 onwards (DST starts second Sunday March)
            if dt_utc.month < 3 or (dt_utc.month == 3 and dt_utc.day < 8):
                offset_hours = -6  # CST
            else:
                offset_hours = -5  # CDT
            from datetime import timedelta as _td
            dt_local = dt_utc + _td(hours=offset_hours)
            return dt_local.replace(tzinfo=None)
        except:
            pass

    # Local datetime (no Z)
    for fmt in ['%Y%m%dT%H%M%S', '%Y%m%d']:
        try:
            return datetime.strptime(dt_str, fmt)
        except:
            continue

    return None


# ─────────────────────────────────────────
# Assignment type inference from title
# ─────────────────────────────────────────
TYPE_PATTERNS = [
    (r'\bfinal exam\b', 'final exam'),
    (r'\bmidterm\b', 'midterm'),
    (r'\bexam\b', 'exam'),
    (r'\bquiz\b', 'quiz'),
    (r'\btest\b', 'exam'),
    (r'\blab\b', 'lab'),
    (r'\bproject\b', 'project'),
    (r'\bpaper\b', 'paper'),
    (r'\bessay\b', 'paper'),
    (r'\bpresentation\b', 'presentation'),
    (r'\bhomework\b|^\s*hw\b', 'homework'),
    (r'\bassignment\b', 'assignment'),
]

DEFAULT_WEIGHTS = {
    'final exam': 35,
    'midterm': 25,
    'exam': 22,
    'quiz': 8,
    'project': 18,
    'lab': 7,
    'paper': 15,
    'presentation': 15,
    'homework': 5,
    'assignment': 5,
}

NOISE_PATTERNS = re.compile(
    r'\b(office hours?|no class|spring break|holiday|reading|syllabus quiz|attendance'
    r'|lecture|discussion section|section|class meeting|review session|exam review'
    r'|cancelled|cancel|optional|survey|course eval|evaluation|feedback'
    r'|zoom|appointment|advising|tutoring|help desk|drop.?in'
    r'|prelecture|pre.?lecture|pre.?lab|pre.?discussion'
    r'|grace period|regrade|regrading)\b'
    r'|\bOH\b',
    re.IGNORECASE
)


def infer_type(summary):
    """Infer assignment type from event title."""
    s = summary.lower()
    for pattern, atype in TYPE_PATTERNS:
        if re.search(pattern, s, re.IGNORECASE):
            return atype
    return 'assignment'


def extract_course_from_summary(summary):
    """
    Canvas formats assignment titles as:
    'Assignment Name [Course Code]' or 'Assignment Name (Course Code)'
    Extract the course code if present.
    """
    m = re.search(r'\[([^\]]+)\]|\(([^)]+)\)', summary)
    if m:
        return (m.group(1) or m.group(2)).strip()
    return None


def extract_points(description):
    """Extract point value from Canvas description if available."""
    if not description:
        return None
    m = re.search(r'[Pp]oints?[:\s]+(\d+)', description)
    if m:
        return int(m.group(1))
    return None


# ─────────────────────────────────────────
# Noise filter — skip non-graded events
# ─────────────────────────────────────────
def is_noise(summary, description=''):
    text = f"{summary} {description}".lower()
    summary_lower = summary.lower()

    # Pattern-based noise
    if NOISE_PATTERNS.search(text):
        return True

    # Skip zero-point items
    pts = extract_points(description)
    if pts is not None and pts == 0:
        return True

    # Canvas sometimes puts instructor availability / OH as calendar events
    # They typically have these markers in the summary
    oh_markers = [
        'office hour', ' oh ', '(oh)', '[oh]',
        'available', 'open hour', 'student hour',
        'drop by', 'walk in', 'walk-in',
        'tutor', 'help room', 'q&a session',
    ]
    for marker in oh_markers:
        if marker in summary_lower:
            return True

    # Skip events that are clearly scheduling/logistics (no assignment keywords)
    # If the title has no graded-item signal at all, skip it
    graded_signal = re.search(
        r'\b(quiz|exam|midterm|final|project|lab|assignment|homework|hw|paper|'
        r'essay|presentation|due|submit|turn in|report|test)\b',
        summary_lower
    )
    # Only apply this aggressive filter if description also has no points info
    if not graded_signal and pts is None:
        # But don't skip if it looks like a named assignment
        named_assignment = re.search(r'\b(p\d+|lab\s*\d+|hw\s*\d+|a\d+)\b', summary_lower)
        if not named_assignment:
            return True

    return False


# ─────────────────────────────────────────
# Course filter
# ─────────────────────────────────────────
def filter_by_courses(deadlines, course_names):
    """
    If user has specified course names, only keep events
    that match one of those courses (fuzzy match).
    """
    if not course_names:
        return deadlines

    filtered = []
    for d in deadlines:
        for cn in course_names:
            cn_clean = re.sub(r'\s+', '', cn).lower()
            dc_clean = re.sub(r'\s+', '', d['course']).lower()
            if cn_clean in dc_clean or dc_clean in cn_clean:
                filtered.append(d)
                break
    return filtered


# ─────────────────────────────────────────
# Public API
# ─────────────────────────────────────────
def parse_canvas_ics(url, course_names=None, default_year=2026):
    """
    Fetch Canvas calendar feed and return list of deadline dicts.
    
    Args:
        url: Canvas calendar feed URL (from Canvas Settings > Calendar)
        course_names: optional list of course name strings to filter by
        default_year: semester year for filtering out-of-range events
    
    Returns:
        list of deadline dicts compatible with scorer.py
    """
    print(f"Fetching Canvas calendar feed...")
    ics_text = fetch_ics(url)
    events = parse_ics(ics_text)
    print(f"  -> Found {len(events)} total calendar events")

    deadlines = []
    skipped = 0

    for event in events:
        summary = event.get('SUMMARY', '').strip()
        dt_str = event.get('DTSTART', '')
        description = event.get('DESCRIPTION', '')

        if not summary or not dt_str:
            continue

        # Skip noise
        if is_noise(summary, description):
            skipped += 1
            continue

        # Parse date
        date_obj = parse_dt(dt_str)
        if not date_obj:
            continue

        # Filter to semester year
        if date_obj.year != default_year:
            continue

        # Extract course from summary
        course = extract_course_from_summary(summary)
        if not course:
            course = 'Unknown Course'

        # Clean summary — remove [Course] tag from description
        clean_summary = re.sub(r'\s*[\[\(][^\]\)]+[\]\)]\s*$', '', summary).strip()

        atype = infer_type(clean_summary)
        weight = DEFAULT_WEIGHTS.get(atype, 5)

        deadlines.append({
            'course': course,
            'date': date_obj,
            'description': clean_summary[:120],
            'type': atype,
            'weight': weight,
            'source': 'canvas'  # tag so we know origin
        })

    print(f"  -> Extracted {len(deadlines)} graded deadlines ({skipped} skipped)")
    for d in deadlines[:10]:
        print(f"     {d['date'].strftime('%b %d')} | {d['course']:15s} | {d['type']:12s} | {d['description'][:50]}")
    if len(deadlines) > 10:
        print(f"     ... and {len(deadlines)-10} more")

    if course_names:
        deadlines = filter_by_courses(deadlines, course_names)
        print(f"  -> After course filter: {len(deadlines)} deadlines")

    deadlines.sort(key=lambda x: x['date'])
    return deadlines


def merge_canvas_with_syllabus(canvas_deadlines, syllabus_deadlines):
    """
    Merge Canvas deadlines (authoritative dates) with syllabus deadlines (authoritative weights).
    
    Strategy:
    1. Canvas dates take priority
    2. For each Canvas deadline, look for a matching syllabus entry to steal the weight
    3. Syllabus-only items are added if Canvas has no matching entry
    """
    merged = []
    syllabus_used = set()

    for cd in canvas_deadlines:
        best_weight = cd['weight']
        best_match_idx = None
        best_score = 0

        # Try to find a matching syllabus entry by course + fuzzy description match
        for i, sd in enumerate(syllabus_deadlines):
            if i in syllabus_used:
                continue

            # Course must roughly match
            cd_course = re.sub(r'\s+', '', cd['course']).lower()
            sd_course = re.sub(r'\s+', '', sd['course']).lower()
            if cd_course not in sd_course and sd_course not in cd_course:
                continue

            # Fuzzy description match — count shared words
            cd_words = set(re.findall(r'\w+', cd['description'].lower()))
            sd_words = set(re.findall(r'\w+', sd['description'].lower()))
            shared = cd_words & sd_words
            score = len(shared) / max(len(cd_words | sd_words), 1)

            # Also match by type
            if cd['type'] == sd['type']:
                score += 0.3

            if score > best_score and score > 0.2:
                best_score = score
                best_match_idx = i
                best_weight = sd['weight']

        if best_match_idx is not None:
            syllabus_used.add(best_match_idx)

        merged.append({
            'course': cd['course'],
            'date': cd['date'],
            'description': cd['description'],
            'type': cd['type'],
            'weight': best_weight,
            'source': cd.get('source', 'canvas')
        })

    # Add syllabus-only items that had no Canvas match
    # But skip if Canvas already has a same-type entry for the same course
    # within 7 days — avoids duplicate Quiz 6 type situations
    for i, sd in enumerate(syllabus_deadlines):
        if i in syllabus_used:
            continue
        # Check if Canvas already has a close match by course+type+nearby date
        duplicate = False
        sd_course = re.sub(r'\s+', '', sd['course']).lower()
        for cd in canvas_deadlines:
            cd_course = re.sub(r'\s+', '', cd['course']).lower()
            course_match = cd_course in sd_course or sd_course in cd_course
            type_match = cd['type'] == sd['type']
            date_diff = abs((cd['date'] - sd['date']).days)
            if course_match and type_match and date_diff <= 7:
                duplicate = True
                break
        if not duplicate:
            merged.append(sd)

    merged.sort(key=lambda x: x['date'])
    print(f"  -> Merged: {len(canvas_deadlines)} Canvas + {len(syllabus_deadlines)} syllabus = {len(merged)} total")
    return merged