import pdfplumber
import anthropic
import json
import os
import re
from datetime import datetime
from html.parser import HTMLParser
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────
# HTML Extractor
# ─────────────────────────────────────────
class HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ['script', 'style']:
            self.skip = True
        if tag in ['br', 'p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'td']:
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


def extract_text_from_html(html_path):
    with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
        html = f.read()
    extractor = HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


def extract_text(file_path):
    if file_path.endswith('.html') or file_path.endswith('.htm'):
        return extract_text_from_html(file_path)
    else:
        return extract_text_from_pdf(file_path)


# ─────────────────────────────────────────
# AI Parser — sends text to Claude API
# ─────────────────────────────────────────
def ai_parse_syllabus(text, course_name, default_year=2026):
    """
    Send syllabus text to Claude and get back structured deadlines as JSON.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Truncate text to avoid token limits — first 6000 chars covers most syllabi
    text_chunk = text[:6000]

    prompt = f"""You are a syllabus parser. Extract ALL graded deadlines, exams, quizzes, projects, assignments, and due dates from the following syllabus text for the course "{course_name}".

Return ONLY a valid JSON array. No explanation, no markdown, no code blocks — just raw JSON.

Each object must have exactly these fields:
- "date": string in "Mon DD" format (e.g. "Feb 26", "Apr 09") using year {default_year}
- "type": one of: "exam", "midterm", "final exam", "quiz", "project", "lab", "assignment", "paper", "presentation", "turn in", "due"
- "description": short description of the assignment (max 80 chars)
- "weight": integer percentage weight (0-100). If not explicitly stated, estimate based on type: final exam=35, midterm=25, project=20, paper=15, quiz=8, lab=7, assignment=5

Rules:
- Include ALL graded items you can find — exams, quizzes, projects, labs, papers, due dates
- If a date range is given, use the END date
- Skip reading assignments, office hours, class meetings with no graded component
- Skip spring break, holidays
- If the same assignment appears multiple times, include it only once with its due date
- Return empty array [] if no deadlines found

Syllabus text:
{text_chunk}"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()

    # Strip any accidental markdown fences
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'^```\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    raw = raw.strip()

    try:
        items = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  [AI parser] JSON parse error: {e}")
        print(f"  [AI parser] Raw response: {raw[:200]}")
        return []

    # Convert to internal deadline format
    deadlines = []
    for item in items:
        try:
            date_str = item.get('date', '').strip()
            # Parse "Feb 26" → datetime
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
                'weight': int(item.get('weight', 10))
            })
        except Exception as e:
            print(f"  [AI parser] Skipping item due to error: {e} — {item}")
            continue

    return deadlines


# ─────────────────────────────────────────
# Public API
# ─────────────────────────────────────────
def parse_syllabus(file_path, course_name, default_year=2026):
    """Main entry point. Uses AI to parse any syllabus format."""
    print(f"Parsing: {file_path}")

    text = extract_text(file_path)

    if not text.strip():
        print(f"  -> No text extracted from {file_path}")
        return []

    deadlines = ai_parse_syllabus(text, course_name, default_year)
    deadlines.sort(key=lambda x: x['date'])

    print(f"  -> Found {len(deadlines)} deadlines for {course_name}")
    for d in deadlines:
        print(f"     {d['date'].strftime('%b %d')} | {d['type']:20s} | {d['description'][:55]}")

    return deadlines