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
# HTML / MHTML Text Extractor
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


# ─────────────────────────────────────────
# File readers
# ─────────────────────────────────────────
def extract_text_from_pdf(pdf_path):
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text


def extract_text_from_html(path):
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        html = f.read()
    extractor = HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


def extract_text_from_mhtml(path):
    """Extract text from .mhtml (web archive) files."""
    with open(path, 'rb') as f:
        msg = email.message_from_bytes(f.read())
    html = ''
    for part in msg.walk():
        if 'html' in part.get_content_type():
            payload = part.get_payload(decode=True)
            if payload:
                html += payload.decode('utf-8', errors='ignore')
    extractor = HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


def extract_text(file_path):
    ext = file_path.lower()
    if ext.endswith('.mhtml') or ext.endswith('.mht'):
        return extract_text_from_mhtml(file_path)
    elif ext.endswith('.html') or ext.endswith('.htm'):
        return extract_text_from_html(file_path)
    else:
        return extract_text_from_pdf(file_path)


# ─────────────────────────────────────────
# Smart text chunking
# Sends the most relevant portions to Claude
# rather than a raw truncation
# ─────────────────────────────────────────
def smart_chunk(text, max_chars=8000):
    """
    Prioritize lines that likely contain dates, grades, or assignment info.
    Always include grading section + schedule section in full.
    """
    lines = text.split('\n')
    high_priority = []
    normal = []

    date_re = re.compile(
        r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s.,]+\d{1,2}'
        r'|\d{1,2}/\d{1,2}'
        r'|\bweek\s+\d+\b',
        re.IGNORECASE
    )
    keyword_re = re.compile(
        r'\b(exam|quiz|midterm|final|project|lab|assignment|hwk|homework|due|paper|'
        r'presentation|test|percent|%|points|grading|schedule)\b',
        re.IGNORECASE
    )

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if date_re.search(line) or keyword_re.search(line):
            high_priority.append(line)
        else:
            normal.append(line)

    # Build chunk: high priority first, fill remainder with normal
    result = '\n'.join(high_priority)
    if len(result) < max_chars:
        remaining = max_chars - len(result)
        result += '\n' + '\n'.join(normal)[:remaining]

    return result[:max_chars]


# ─────────────────────────────────────────
# AI Parser
# ─────────────────────────────────────────
def ai_parse_syllabus(text, course_name, default_year=2026):
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    chunk = smart_chunk(text)

    prompt = f"""You are an expert academic syllabus parser. Extract every graded deadline from this syllabus for the course "{course_name}".

Return ONLY a raw JSON array — no markdown, no explanation, no code fences. Just the array.

Each object must have exactly these fields:
- "date": the DEADLINE date as "Mon DD" (e.g. "Feb 26"). For date ranges use the CLOSING/DUE date.
- "type": one of: "exam", "midterm", "final exam", "quiz", "project", "lab", "assignment", "paper", "presentation", "homework"
- "description": concise name of the assignment, max 80 chars (e.g. "Quiz 3", "Midterm 1", "Project 2 due")
- "weight": integer 0-100 representing this item's % of final grade. If the syllabus says "3 exams @ 60% total", each exam = 20. If not stated, estimate: final exam=35, midterm=20, quiz=8, project=15, lab=5, assignment=5, homework=5.

CRITICAL RULES:
- Read ALL sections carefully: grading tables, course schedules, week-by-week breakdowns, inline prose ("the exam will be on Feb 10")
- For quizzes/labs that repeat weekly, include EACH ONE with its specific date
- For exams stated as date ranges (opens Mon, closes Wed), use the CLOSING date
- If a "Week N" schedule is used and semester starts Jan 20, calculate actual dates (Week 1=Jan 20, Week 2=Jan 27, etc.)
- Skip: office hours, reading assignments with no grade, attendance-only items, class meetings
- Do NOT skip: any exam, quiz, project milestone, paper, lab with a due date
- Return [] if genuinely nothing graded with dates found

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
            print(f"  [AI parser] Skipping item: {e} — {item}")

    return deadlines


# ─────────────────────────────────────────
# Public API
# ─────────────────────────────────────────
def parse_syllabus(file_path, course_name, default_year=2026):
    print(f"Parsing: {file_path}")

    text = extract_text(file_path)

    if not text.strip():
        print(f"  -> No text extracted from {file_path}")
        return []

    deadlines = ai_parse_syllabus(text, course_name, default_year)
    deadlines.sort(key=lambda x: x['date'])

    print(f"  -> Found {len(deadlines)} deadlines for {course_name}")
    for d in deadlines:
        print(f"     {d['date'].strftime('%b %d')} | {d['type']:20s} | {d['description'][:60]}")

    return deadlines