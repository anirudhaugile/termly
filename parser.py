import pdfplumber
import anthropic
import json
import os
import re
import email
from datetime import datetime
from html.parser import HTMLParser
from dotenv import load_dotenv

load_dotenv()


# ─────────────────────────────────────────
# Text Extractors
# ─────────────────────────────────────────
class HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ['script', 'style']:
            self.skip = True
        if tag in ['br', 'p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'td', 'th']:
            self.text.append('\n')

    def handle_endtag(self, tag):
        if tag in ['script', 'style']:
            self.skip = False

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.text.append(data.strip())

    def get_text(self):
        return '\n'.join(self.text)


def extract_text_from_pdf(path):
    text = ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"
    return text


def extract_text_from_html(path):
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        html = f.read()
    e = HTMLTextExtractor()
    e.feed(html)
    return e.get_text()


def extract_text_from_mhtml(path):
    with open(path, 'rb') as f:
        msg = email.message_from_bytes(f.read())
    html = ''
    for part in msg.walk():
        if 'html' in part.get_content_type():
            payload = part.get_payload(decode=True)
            if payload:
                html += payload.decode('utf-8', errors='ignore')
    e = HTMLTextExtractor()
    e.feed(html)
    return e.get_text()


def extract_text(file_path):
    ext = file_path.lower()
    if ext.endswith(('.mhtml', '.mht')):
        return extract_text_from_mhtml(file_path)
    elif ext.endswith(('.html', '.htm')):
        return extract_text_from_html(file_path)
    else:
        return extract_text_from_pdf(file_path)


# ─────────────────────────────────────────
# Smart chunking — head + tail + keywords
# Exam dates are almost always near the END
# of a syllabus, so we must include the tail
# ─────────────────────────────────────────
def smart_chunk(text, max_chars=12000):
    # Always include: first 3000 chars (course info, grading weights)
    # + last 4000 chars (schedule, exam dates — almost always at end)
    # + middle keyword lines (anything with dates/assignment keywords)

    head = text[:3000]
    tail = text[-4000:] if len(text) > 4000 else ''

    keyword_re = re.compile(
        r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*'
        r'|\d{1,2}/\d{1,2}'
        r'|\bweek\s*\d+\b'
        r'|\b(exam|quiz|midterm|final|project|lab|assignment|homework|due|paper|presentation|test)\b',
        re.IGNORECASE
    )

    middle_lines = []
    middle_text = text[3000:max(3000, len(text)-4000)]
    for line in middle_text.split('\n'):
        if keyword_re.search(line) and len(line.strip()) > 5:
            middle_lines.append(line.strip())

    middle = '\n'.join(middle_lines)

    # Combine, deduplicate
    combined = head + '\n\n--- MIDDLE KEY LINES ---\n' + middle + '\n\n--- END OF SYLLABUS ---\n' + tail
    return combined[:max_chars]


# ─────────────────────────────────────────
# AI Parser
# ─────────────────────────────────────────
def ai_parse_syllabus(text, course_name, default_year=2026):
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    chunk = smart_chunk(text)

    prompt = f"""You are an expert academic syllabus parser. Extract every graded deadline from this syllabus for the course "{course_name}".

Return ONLY a raw JSON array — no markdown, no explanation, no code fences.

Each object must have exactly these fields:
- "date": the DEADLINE date as "Mon DD" e.g. "Feb 26". For date ranges use the CLOSING date.
- "type": one of: "exam", "midterm", "final exam", "quiz", "project", "lab", "assignment", "paper", "presentation", "homework"
- "description": concise name, max 80 chars e.g. "Quiz 3", "Midterm 1", "Project 2"
- "weight": integer % of final grade. If syllabus says "3 exams = 60% total", each = 20. Estimates if not stated: final exam=35, midterm=20, quiz=8, project=15, lab=5, assignment=5, homework=5

CRITICAL RULES:
- Read ALL sections: grading tables, schedules, week plans, AND inline prose sentences like "The exam will be on Feb. 10"
- Exam dates are often stated as prose near the END of the document — read carefully
- For each quiz/lab that repeats weekly, include EACH ONE with its specific date
- For date ranges (opens Mon, closes Wed) → use the CLOSING date
- Skip: office hours, readings with no grade, class meetings with no submission
- If no specific dates exist (all on Canvas), return []

Syllabus text:
{chunk}"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'^```\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    raw = raw.strip()

    try:
        items = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  [AI parser] JSON error: {e}")
        print(f"  [AI parser] Raw: {raw[:300]}")
        return []

    deadlines = []
    for item in items:
        try:
            date_str = str(item.get('date', '')).strip()
            date_obj = None
            for fmt in ['%b %d %Y', '%B %d %Y']:
                try:
                    date_obj = datetime.strptime(f"{date_str} {default_year}", fmt)
                    break
                except:
                    continue
            if not date_obj:
                continue

            deadlines.append({
                'course': course_name,
                'date': date_obj,
                'description': str(item.get('description', ''))[:120],
                'type': str(item.get('type', 'due')).lower(),
                'weight': max(1, min(100, int(item.get('weight', 10))))
            })
        except Exception as e:
            print(f"  [AI parser] Skipping: {e} — {item}")

    return deadlines


# ─────────────────────────────────────────
# Public API — supports multiple files per course
# ─────────────────────────────────────────
def parse_syllabus(file_paths, course_name, default_year=2026):
    """
    file_paths: str (single file) or list of str (multiple files per course)
    Merges all text from all files before sending to AI.
    """
    if isinstance(file_paths, str):
        file_paths = [file_paths]

    combined_text = ''
    for path in file_paths:
        print(f"  Reading: {path}")
        text = extract_text(path)
        if text.strip():
            combined_text += f'\n\n=== FILE: {os.path.basename(path)} ===\n' + text
        else:
            print(f"  -> No text extracted from {path}")

    if not combined_text.strip():
        print(f"  -> No text extracted for {course_name}")
        return []

    print(f"Parsing {course_name} ({len(file_paths)} file(s), {len(combined_text)} chars total)...")
    deadlines = ai_parse_syllabus(combined_text, course_name, default_year)
    deadlines.sort(key=lambda x: x['date'])

    print(f"  -> Found {len(deadlines)} deadlines for {course_name}")
    for d in deadlines:
        print(f"     {d['date'].strftime('%b %d')} | {d['type']:20s} | {d['description'][:60]}")

    return deadlines