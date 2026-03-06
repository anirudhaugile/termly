import pdfplumber
import re
from datetime import datetime
from html.parser import HTMLParser

class HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ['script', 'style']:
            self.skip = True
        if tag in ['br', 'p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'h4']:
            self.text.append('\n')

    def handle_endtag(self, tag):
        if tag in ['script', 'style']:
            self.skip = False

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.text.append(data.strip())

    def get_text(self):
        return '\n'.join(self.text)


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


MONTH_PATTERN = (
    r'(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
    r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
)

UW_DATE = re.compile(
    r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*[.,]*\s*' + MONTH_PATTERN + r'[.,]*\s+(\d{1,2})',
    re.IGNORECASE
)

MONTH_DAY = re.compile(
    MONTH_PATTERN + r'[.,]*\s+(\d{1,2})(?:st|nd|rd|th)?[,:\s]',
    re.IGNORECASE
)

NUMERIC_DATE = re.compile(r'\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b')

WEEK_RANGE = re.compile(
    MONTH_PATTERN + r'[.,]*\s+(\d{1,2})[,\s]+\d{1,2}',
    re.IGNORECASE
)

# Lines that look like dates but are NOT deadlines
NOISE_RE = re.compile(
    r'visitor pre-read|visitor pre-listen|no class|no in-person|spring break'
    r'|office hours|^\s*[\•\-\*]\s*(read|watch|listen|view|review|check)'
    r'|edition\s*\(|wiley|wisc\.edu|isbn|liveright|sage pub'
    r'|overdue:',  # podcast/reading labels
    re.IGNORECASE
)

# Dates that are clearly publication years or edition dates (e.g. "November 2, 2015")
PUBLICATION_RE = re.compile(r'edition|published|wiley|isbn|press,?\s*\d{4}', re.IGNORECASE)

WEIGHT_RE = re.compile(r'(\d{1,3})\s*%')

# Ordered by priority — more specific phrases first
ASSIGNMENT_KEYWORDS = [
    'final exam', 'final project', 'midterm exam', 'midterm',
    'in-class exam', 'written exam', 'in class written exam',
    'short paper', 'final', 'exam', 'quiz', 'test',
    'project', 'paper', 'essay', 'presentation',
    'turn in', 'submit', 'submission', 'due',
    'lab exercise', 'lab', 'homework', 'hw', 'assignment',
]

KEYWORD_WEIGHTS = {
    'final exam': 35,
    'final project': 30,
    'midterm exam': 25,
    'in-class exam': 25,
    'written exam': 25,
    'in class written exam': 25,
    'midterm': 25,
    'final': 22,
    'exam': 22,
    'test': 20,
    'project': 20,
    'short paper': 15,
    'paper': 15,
    'essay': 15,
    'presentation': 15,
    'turn in': 12,
    'submit': 10,
    'submission': 10,
    'due': 10,
    'quiz': 8,
    'lab exercise': 8,
    'lab': 7,
    'homework': 5,
    'hw': 5,
    'assignment': 5,
}


def find_keyword(text):
    text_lower = text.lower()
    for kw in ASSIGNMENT_KEYWORDS:
        if kw in text_lower:
            return kw
    return None


def parse_date(line, default_year=2026):
    # Skip lines that are clearly not deadline lines
    if NOISE_RE.search(line):
        return None
    # Skip publication dates: "November 2, 2015" style (year present and < 2025)
    year_match = re.search(r'\b(19\d{2}|20[01]\d|202[0-4])\b', line)
    if year_match:
        return None  # historical year — skip

    m = UW_DATE.search(line)
    if m:
        return _make_date(m.group(1), m.group(2), default_year)

    m = MONTH_DAY.search(line)
    if m:
        return _make_date(m.group(1), m.group(2), default_year)

    m = WEEK_RANGE.search(line)
    if m:
        return _make_date(m.group(1), m.group(2), default_year)

    m = NUMERIC_DATE.search(line)
    if m:
        month_n, day_n = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else default_year
        if year < 2025:
            return None
        if year < 100:
            year += 2000
        try:
            return datetime(year, month_n, day_n)
        except:
            return None

    return None


def _make_date(month_str, day_str, year):
    for fmt in ['%B %d %Y', '%b %d %Y']:
        try:
            return datetime.strptime(f"{month_str} {day_str} {year}", fmt)
        except:
            continue
    return None


def extract_deadlines(text, course_name, default_year=2026):
    deadlines = []
    lines = text.split('\n')

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue

        found_date = parse_date(line, default_year)
        if not found_date:
            continue

        # Window: this line + next 6
        window = lines[i: min(i + 7, len(lines))]
        window_text = ' '.join(w.strip() for w in window)

        found_keyword = find_keyword(window_text)
        if not found_keyword:
            continue

        # Prefer a more descriptive line from the window
        description = line
        for ctx_line in window:
            ctx_line = ctx_line.strip()
            if find_keyword(ctx_line) and len(ctx_line) > len(description):
                description = ctx_line

        # Weight
        weight = KEYWORD_WEIGHTS.get(found_keyword, 10)
        wm = WEIGHT_RE.search(window_text)
        if wm:
            weight = int(wm.group(1))

        # Dedup: same course + date + keyword
        duplicate = any(
            d['course'] == course_name
            and d['date'] == found_date
            and d['type'] == found_keyword
            for d in deadlines
        )
        if duplicate:
            continue

        deadlines.append({
            'course': course_name,
            'date': found_date,
            'description': description[:120],
            'type': found_keyword,
            'weight': weight
        })

    return deadlines


def parse_syllabus(file_path, course_name, default_year=2026):
    """Main entry point. Accepts PDF or HTML path. Returns list of deadline dicts."""
    print(f"Parsing: {file_path}")
    text = extract_text(file_path)
    deadlines = extract_deadlines(text, course_name, default_year)
    print(f"  -> Found {len(deadlines)} deadlines for {course_name}")
    for d in deadlines:
        print(f"     {d['date'].strftime('%b %d')} | {d['type']:20s} | {d['description'][:55]}")
    return deadlines