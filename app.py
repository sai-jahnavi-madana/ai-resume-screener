from flask import Flask, render_template, request, jsonify, session, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

import openai
import PyPDF2
import io
import os
import json
import re
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import matplotlib
from sqlalchemy import inspect, text
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import base64
from datetime import datetime, timedelta

load_dotenv()

def get_database_uri():
    url = os.getenv('DATABASE_URL', '').strip()
    if url:
        if url.startswith('postgres://'):
            url = url.replace('postgres://', 'postgresql://', 1)
        return url
    instance_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
    os.makedirs(instance_dir, exist_ok=True)
    db_file = os.path.join(instance_dir, 'resume_screener.db')
    return 'sqlite:///' + db_file.replace('\\', '/')

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY') or 'dev-secret-change-before-deploy'
app.config['SQLALCHEMY_DATABASE_URI'] = get_database_uri()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_UPLOAD_MB', '16')) * 1024 * 1024

if os.getenv('FLASK_ENV') == 'production':
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_HTTPONLY'] = True

db = SQLAlchemy(app)

GUEST_FREE_ATTEMPTS = int(os.getenv('GUEST_FREE_ATTEMPTS', '2'))
BLACK = HexColor('#000000')
WHITE = HexColor('#FFFFFF')
LIGHT_ROW = HexColor('#F5F5F5')

# ── GUEST TRIAL ──
def is_logged_in():
    return 'user_id' in session

def guest_attempts_used():
    return int(session.get('guest_screen_count', 0))

def guest_attempts_remaining():
    if is_logged_in():
        return None
    return max(0, GUEST_FREE_ATTEMPTS - guest_attempts_used())

def guest_limit_response():
    return jsonify({
        'error': f'Free trial used ({GUEST_FREE_ATTEMPTS} screenings). Sign up or sign in to continue.',
        'signup_required': True,
        'attempts_used': guest_attempts_used(),
        'attempts_limit': GUEST_FREE_ATTEMPTS,
    }), 403

def record_guest_attempt():
    if not is_logged_in():
        session['guest_screen_count'] = guest_attempts_used() + 1

def pdf_escape(text):
    return (text or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

# ── MODELS ──
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    verification_code = db.Column(db.String(6), nullable=True)
    verification_expires = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    screenings = db.relationship('Screening', backref='user', lazy=True)

VERIFICATION_MINUTES = int(os.getenv('VERIFICATION_CODE_MINUTES', '15'))

def migrate_user_table():
    if not inspect(db.engine).has_table('user'):
        return
    cols = {c['name'] for c in inspect(db.engine).get_columns('user')}
    with db.engine.begin() as conn:
        if 'email_verified' not in cols:
            conn.execute(text('ALTER TABLE user ADD COLUMN email_verified BOOLEAN DEFAULT 1'))
            conn.execute(text('UPDATE user SET email_verified = 1 WHERE email_verified IS NULL'))
        if 'verification_code' not in cols:
            conn.execute(text('ALTER TABLE user ADD COLUMN verification_code VARCHAR(6)'))
        if 'verification_expires' not in cols:
            conn.execute(text('ALTER TABLE user ADD COLUMN verification_expires DATETIME'))

def get_current_user():
    if not is_logged_in():
        return None
    return db.session.get(User, session['user_id'])

def login_user(user):
    session['user_id'] = user.id
    session['user_name'] = user.name
    session.pop('guest_screen_count', None)

def generate_verification_code():
    return f'{secrets.randbelow(900000) + 100000:06d}'

def set_verification_code(user):
    user.verification_code = generate_verification_code()
    user.verification_expires = datetime.utcnow() + timedelta(minutes=VERIFICATION_MINUTES)
    db.session.commit()
    return user.verification_code

def send_verification_email(user, code):
    mail_server = os.getenv('MAIL_SERVER', '').strip()
    mail_port = int(os.getenv('MAIL_PORT', '587'))
    mail_user = os.getenv('MAIL_USERNAME', '').strip()
    mail_pass = os.getenv('MAIL_PASSWORD', '').strip()
    mail_from = os.getenv('MAIL_FROM', mail_user).strip() or 'noreply@resume-screener.local'

    subject = 'Your verification code — AI Resume Screener'
    body = f"""Hi {user.name},

Your email verification code is:

  {code}

This code expires in {VERIFICATION_MINUTES} minutes.

If you did not sign up, ignore this email.

— AI Resume Screener
"""
    if not mail_server or not mail_user or not mail_pass:
        print(f'\n[EMAIL DEV] To: {user.email} | Code: {code}\n')
        return False, 'dev_console'

    msg = MIMEMultipart()
    msg['From'] = mail_from
    msg['To'] = user.email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    with smtplib.SMTP(mail_server, mail_port) as server:
        server.starttls()
        server.login(mail_user, mail_pass)
        server.sendmail(mail_from, [user.email], msg.as_string())
    return True, 'sent'

def verified_user_required():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not logged in'}), 401
    if not user.email_verified:
        return jsonify({
            'error': 'Please verify your email with the 6-digit code we sent you.',
            'verification_required': True,
            'email': user.email,
        }), 403
    return None

class Screening(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    job_desc = db.Column(db.Text, nullable=False)
    results = db.Column(db.Text, nullable=False)
    total_resumes = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text, default='{}')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ── EXTRACT PDF ──
def extract_text(pdf_file):
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(pdf_file.read()))
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text.strip()
    except:
        return ""

# ── API KEY (user-provided on website, optional .env fallback for local dev) ──
def resolve_openai_api_key(form_value=None):
    key = (form_value or '').strip()
    if key:
        session['openai_api_key'] = key
        return key
    key = (session.get('openai_api_key') or '').strip()
    if key:
        return key
    return (os.getenv('OPENAI_API_KEY') or '').strip()

# ── LOCAL RANKING (no API key) ──
STOPWORDS = {
    'a', 'an', 'the', 'and', 'or', 'for', 'with', 'in', 'on', 'at', 'to', 'of', 'is', 'are',
    'was', 'be', 'by', 'as', 'from', 'that', 'this', 'we', 'you', 'our', 'will', 'have', 'has',
    'been', 'their', 'they', 'your', 'all', 'any', 'can', 'may', 'not', 'but', 'if', 'than',
    'into', 'such', 'other', 'about', 'over', 'more', 'most', 'some', 'than', 'then', 'them',
    'who', 'what', 'when', 'where', 'which', 'while', 'using', 'used', 'use', 'work', 'working',
    'experience', 'years', 'year', 'role', 'team', 'looking', 'required', 'requirements',
}

COMMON_SKILLS = [
    'python', 'java', 'javascript', 'typescript', 'react', 'vue', 'angular', 'node.js', 'nodejs',
    'flask', 'django', 'fastapi', 'spring', 'sql', 'mysql', 'postgresql', 'mongodb', 'redis',
    'aws', 'azure', 'gcp', 'docker', 'kubernetes', 'git', 'linux', 'html', 'css', 'rest api',
    'machine learning', 'deep learning', 'nlp', 'tensorflow', 'pytorch', 'scikit-learn',
    'pandas', 'numpy', 'tableau', 'power bi', 'excel', 'r programming', 'spark', 'hadoop',
    'c++', 'c#', '.net', 'php', 'ruby', 'golang', 'go', 'rust', 'scala', 'agile', 'scrum',
    'ci/cd', 'jenkins', 'terraform', 'ansible', 'figma', 'selenium', 'jira', 'kotlin', 'swift',
    'object-oriented', 'oop', 'api', 'microservices', 'etl', 'data analysis', 'data visualization',
    'statistics', 'computer vision', 'generative ai', 'llm', 'openai', 'bert', 'transformers',
]
DEGREE_KEYWORDS = {
    'phd': ['phd', 'ph.d', 'doctorate'],
    'masters': ['m.tech', 'mtech', 'm.s', 'ms ', 'mca', 'mba', 'master of', 'masters'],
    'bachelors': ['b.tech', 'btech', 'b.e', 'b.sc', 'bsc', 'bca', 'bachelor of', 'bachelors'],
}

def extract_experience_years(text):
    text_lower = text.lower()
    patterns = [
        r'(\d+(?:\.\d+)?)\+?\s*(?:years|yrs|year)\s*(?:of)?\s*experience',
        r'experience\s*(?:of)?\s*(\d+(?:\.\d+)?)\+?\s*(?:years|yrs|year)',
    ]
    years_found = []
    for p in patterns:
        for m in re.findall(p, text_lower):
            try:
                years_found.append(float(m))
            except ValueError:
                continue
    return max(years_found) if years_found else None

def extract_required_experience(job_desc):
    return extract_experience_years(job_desc)

def detect_highest_degree(text):
    text_lower = text.lower()
    for level in ['phd', 'masters', 'bachelors']:
        for kw in DEGREE_KEYWORDS[level]:
            if kw in text_lower:
                return level
    return None

def degree_meets_requirement(job_desc, resume_text):
    rank = {'bachelors': 1, 'masters': 2, 'phd': 3}
    jd_degree = detect_highest_degree(job_desc)
    if not jd_degree:
        return True, None
    resume_degree = detect_highest_degree(resume_text)
    if not resume_degree:
        return False, jd_degree
    return rank.get(resume_degree, 0) >= rank.get(jd_degree, 0), jd_degree
def find_skills_in_text(text):
    text_lower = text.lower()
    found = []
    for skill in sorted(COMMON_SKILLS, key=len, reverse=True):
        if skill in text_lower and skill not in found:
            found.append(skill)
    return found

def extract_keywords(text):
    tokens = re.findall(r'[a-zA-Z][a-zA-Z0-9+#.]{1,}', text.lower())
    return [t for t in tokens if len(t) >= 3 and t not in STOPWORDS]

def rank_resumes_local(job_desc, resumes_dict):
    job_skills = find_skills_in_text(job_desc)
    job_keywords = list(dict.fromkeys(extract_keywords(job_desc)))
    criteria = job_skills if job_skills else job_keywords[:40]

    results = []
    for name, resume_text in resumes_dict.items():
        resume_lower = resume_text.lower()
        resume_skills = find_skills_in_text(resume_text)

        if criteria and job_skills:
            matched = [s for s in job_skills if s in resume_skills or s in resume_lower]
            matched = list(dict.fromkeys(matched))
            missing = [s for s in job_skills if s not in matched][:5]
            score = min(100, round(len(matched) / len(job_skills) * 100)) if job_skills else 50
        elif criteria:
            matched = [k for k in criteria if k in resume_lower]
            matched = list(dict.fromkeys(matched))
            missing = [k for k in criteria if k not in matched][:5]
            score = min(100, round(len(matched) / len(criteria) * 100)) if criteria else 50
        else:
            matched, missing, score = [], [], 50

        matches_str = ', '.join(s.title() for s in matched[:5]) or 'Limited keyword overlap'
        missing_str = ', '.join(s.title() for s in missing[:3]) or 'None identified'
        if score >= 70:
            summary = f'Strong skill match — {len(matched)} job requirements found in resume.'
        elif score >= 50:
            summary = f'Moderate match — {len(matched)} overlapping skills/keywords.'
        else:
            summary = f'Weak match — only {len(matched)} requirements found in resume.'

        results.append({
            'name': name,
            'score': score,
            'matches': matches_str,
            'missing': missing_str,
            'summary': summary,
        })

    return sorted(results, key=lambda x: x['score'], reverse=True)

# ── OPENAI ERROR MESSAGES ──
def friendly_openai_error(exc):
    msg = str(exc).lower()
    if 'insufficient_quota' in msg or 'exceeded your current quota' in msg:
        return (
            'This OpenAI API key has no credits left. Add payment or credits at '
            'platform.openai.com/account/billing, or paste a different API key above.'
        )
    if 'rate_limit' in msg or 'error code: 429' in msg:
        return 'OpenAI rate limit reached. Wait a minute and try again, or use another API key.'
    if 'invalid_api_key' in msg or 'incorrect api key' in msg:
        return 'Invalid API key. Create a new one at platform.openai.com/api-keys'
    return 'OpenAI request failed. Check your API key and billing, then try again.'

# ── AI RANKING ──
def rank_resumes_local(job_desc, resumes_dict):
    job_skills = find_skills_in_text(job_desc)
    job_keywords = list(dict.fromkeys(extract_keywords(job_desc)))
    criteria = job_skills if job_skills else job_keywords[:40]
    required_exp = extract_required_experience(job_desc)

    results = []
    for name, resume_text in resumes_dict.items():
        resume_lower = resume_text.lower()
        resume_skills = find_skills_in_text(resume_text)

        if criteria and job_skills:
            matched = [s for s in job_skills if s in resume_skills or s in resume_lower]
            matched = list(dict.fromkeys(matched))
            missing = [s for s in job_skills if s not in matched][:5]
            skill_score = (len(matched) / len(job_skills) * 100) if job_skills else 50
        elif criteria:
            matched = [k for k in criteria if k in resume_lower]
            matched = list(dict.fromkeys(matched))
            missing = [k for k in criteria if k not in matched][:5]
            skill_score = (len(matched) / len(criteria) * 100) if criteria else 50
        else:
            matched, missing, skill_score = [], [], 50

        candidate_exp = extract_experience_years(resume_text)
        exp_note = None
        exp_score = 100
        if required_exp is not None:
            if candidate_exp is None:
                exp_score = 70
                exp_note = f'{required_exp:g}+ yrs required (resume experience not detected)'
            elif candidate_exp >= required_exp:
                exp_score = 100
                exp_note = f'Meets experience requirement ({candidate_exp:g} yrs >= {required_exp:g} yrs)'
            else:
                shortfall = required_exp - candidate_exp
                exp_score = max(40, 100 - shortfall * 20)
                exp_note = f'Below required experience ({candidate_exp:g} yrs < {required_exp:g} yrs)'

        edu_ok, jd_degree = degree_meets_requirement(job_desc, resume_text)
        edu_score = 100
        edu_note = None
        if jd_degree:
            if edu_ok:
                edu_note = f'Meets education requirement ({jd_degree.title()})'
            else:
                edu_score = 70
                edu_note = f'Below required education ({jd_degree.title()} preferred)'

        if required_exp is not None or jd_degree:
            final_score = round(skill_score * 0.7 + exp_score * 0.2 + edu_score * 0.1)
        else:
            final_score = round(skill_score)
        final_score = max(0, min(100, final_score))

        matches_str = ', '.join(s.title() for s in matched[:5]) or 'Limited keyword overlap'
        missing_str = ', '.join(s.title() for s in missing[:3]) or 'None identified'

        if final_score >= 70:
            summary = f'Strong skill match — {len(matched)} job requirements found in resume.'
        elif final_score >= 50:
            summary = f'Moderate match — {len(matched)} overlapping skills/keywords.'
        else:
            summary = f'Weak match — only {len(matched)} requirements found in resume.'

        extra_notes = [n for n in [exp_note, edu_note] if n]
        if extra_notes:
            summary += ' ' + ' '.join(extra_notes) + '.'

        results.append({
            'name': name,
            'score': final_score,
            'matches': matches_str,
            'missing': missing_str,
            'summary': summary,
        })

    return sorted(results, key=lambda x: x['score'], reverse=True)

# ── GENERATE CHART ──
def generate_chart(results):
    names = [r['name'].replace('.pdf','')[:15] for r in results]
    scores = [r['score'] for r in results]
    colors_list = ['#3dd6ac' if s >= 70 else '#fbbf24' if s >= 50 else '#f97e72' for s in scores]

    fig, ax = plt.subplots(figsize=(10, max(4, len(names) * 0.6)))
    fig.patch.set_facecolor('#111827')
    ax.set_facecolor('#1a2235')

    bars = ax.barh(names, scores, color=colors_list, height=0.5, edgecolor='none')
    for bar, score in zip(bars, scores):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height()/2,
                f'{score}', va='center', ha='left', color='#e8edf5', fontsize=11, fontweight='bold')

    ax.set_xlim(0, 110)
    ax.set_xlabel('Match Score', color='#8a9ab8', fontsize=11)
    ax.tick_params(colors='#8a9ab8')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_color('#1f2d47')
    ax.spines['left'].set_color('#1f2d47')
    plt.yticks(color='#e8edf5', fontsize=10)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='#111827')
    buf.seek(0)
    chart_b64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close()
    return chart_b64

# ── GENERATE PDF (clean black text on white) ──
def generate_pdf_report(results, job_desc):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        rightMargin=54, leftMargin=54, topMargin=54, bottomMargin=54,
    )
    story = []

    title_style = ParagraphStyle(
        'Title', fontSize=22, fontName='Helvetica-Bold',
        textColor=BLACK, spaceAfter=6, leading=26,
    )
    sub_style = ParagraphStyle(
        'Sub', fontSize=11, fontName='Helvetica',
        textColor=BLACK, spaceAfter=16, leading=14,
    )
    heading_style = ParagraphStyle(
        'Heading', fontSize=13, fontName='Helvetica-Bold',
        textColor=BLACK, spaceAfter=8, spaceBefore=14, leading=16,
    )
    body_style = ParagraphStyle(
        'Body', fontSize=10, fontName='Helvetica',
        textColor=BLACK, spaceAfter=6, leading=14,
    )
    small_style = ParagraphStyle(
        'Small', fontSize=9, fontName='Helvetica',
        textColor=BLACK, spaceAfter=4, leading=12,
    )

    story.append(Paragraph("Resume Screening Report", title_style))
    story.append(Paragraph(f"Generated on {datetime.now().strftime('%d %B %Y at %I:%M %p')}", sub_style))
    story.append(Paragraph(f"Total candidates screened: {len(results)}", body_style))
    story.append(Spacer(1, 10))
    story.append(Paragraph("Job Description", heading_style))
    jd = job_desc[:800] + ('...' if len(job_desc) > 800 else '')
    story.append(Paragraph(pdf_escape(jd), body_style))
    story.append(Spacer(1, 14))
    story.append(Paragraph("Ranking Summary", heading_style))

    table_data = [['Rank', 'Candidate', 'Score', 'Matching Skills', 'Missing Skills']]
    for i, r in enumerate(results):
        table_data.append([
            f'{i + 1}',
            r['name'].replace('.pdf', '')[:28],
            f"{r['score']}/100",
            r['matches'][:45],
            r['missing'][:35],
        ])

    table = Table(table_data, colWidths=[36, 128, 52, 155, 115], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT_ROW),
        ('TEXTCOLOR', (0, 0), (-1, -1), BLACK),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, LIGHT_ROW]),
        ('GRID', (0, 0), (-1, -1), 0.5, BLACK),
        ('ROWHEIGHT', (0, 0), (-1, -1), 24),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 9),
    ]))
    story.append(table)
    story.append(Spacer(1, 18))
    story.append(Paragraph("Detailed Analysis", heading_style))

    for i, r in enumerate(results):
        name = pdf_escape(r['name'].replace('.pdf', ''))
        story.append(Paragraph(f"{i + 1}. {name} — Score: {r['score']}/100", heading_style))
        story.append(Paragraph(f"<b>Summary:</b> {pdf_escape(r['summary'])}", body_style))
        story.append(Paragraph(f"<b>Matching skills:</b> {pdf_escape(r['matches'])}", body_style))
        story.append(Paragraph(f"<b>Missing skills:</b> {pdf_escape(r['missing'])}", body_style))
        story.append(Spacer(1, 10))

    story.append(Spacer(1, 12))
    story.append(Paragraph("Sai Jahnavi Madana · NIT Warangal", small_style))
    doc.build(story)
    buf.seek(0)
    return buf

# ── ROUTES ──
@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

@app.route('/')
def index():
    user = None
    u = get_current_user()
    if u and u.email_verified:
        user = u
    return render_template(
        'index.html',
        user=user,
        guest_attempts_limit=GUEST_FREE_ATTEMPTS,
    )

@app.route('/guest_status')
def guest_status():
    remaining = guest_attempts_remaining()
    u = get_current_user()
    logged_in = bool(u and u.email_verified)
    return jsonify({
        'logged_in': logged_in,
        'name': u.name if logged_in else None,
        'attempts_limit': GUEST_FREE_ATTEMPTS,
        'attempts_used': guest_attempts_used() if not is_logged_in() else 0,
        'attempts_remaining': remaining,
    })

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    if not name or not email or len(password) < 6:
        return jsonify({'error': 'Please fill all fields (password min 6 chars)'}), 400

    existing = User.query.filter_by(email=email).first()
    if existing and existing.email_verified:
        return jsonify({'error': 'Email already registered. Sign in instead.'}), 400

    if existing:
        user = existing
        user.name = name
        user.password = generate_password_hash(password)
    else:
        user = User(
            name=name,
            email=email,
            password=generate_password_hash(password),
            email_verified=False,
        )
        db.session.add(user)
    db.session.commit()

    code = set_verification_code(user)
    sent, channel = send_verification_email(user, code)
    payload = {
        'verification_required': True,
        'email': email,
        'message': f'We sent a 6-digit code to {email}. Enter it below to verify your account.',
        'expires_minutes': VERIFICATION_MINUTES,
    }
    if channel == 'dev_console' and os.getenv('FLASK_DEBUG', 'true').lower() in ('1', 'true', 'yes'):
        payload['dev_code'] = code
        payload['message'] += ' (Dev: code printed in server terminal.)'
    return jsonify(payload)

@app.route('/verify_email', methods=['POST'])
def verify_email():
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    code = data.get('code', '').strip()
    if not email or not code:
        return jsonify({'error': 'Email and verification code are required'}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'error': 'No account found for this email'}), 404
    if user.email_verified:
        login_user(user)
        return jsonify({'success': True, 'name': user.name})

    if not user.verification_code or user.verification_code != code:
        return jsonify({'error': 'Invalid verification code'}), 400
    if not user.verification_expires or datetime.utcnow() > user.verification_expires:
        return jsonify({'error': 'Code expired. Click Resend code.'}), 400

    user.email_verified = True
    user.verification_code = None
    user.verification_expires = None
    db.session.commit()
    login_user(user)
    return jsonify({'success': True, 'name': user.name})

@app.route('/resend_verification', methods=['POST'])
def resend_verification():
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'error': 'No account found for this email'}), 404
    if user.email_verified:
        return jsonify({'error': 'Email is already verified. You can sign in.'}), 400

    code = set_verification_code(user)
    send_verification_email(user, code)
    payload = {
        'success': True,
        'message': f'New code sent to {email}.',
        'expires_minutes': VERIFICATION_MINUTES,
    }
    if os.getenv('FLASK_DEBUG', 'true').lower() in ('1', 'true', 'yes') and not os.getenv('MAIL_SERVER'):
        payload['dev_code'] = code
    return jsonify(payload)

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password, password):
        return jsonify({'error': 'Invalid email or password'}), 400
    if not user.email_verified:
        code = set_verification_code(user)
        send_verification_email(user, code)
        payload = {
            'verification_required': True,
            'email': email,
            'error': 'Email not verified yet. Enter the code we sent to your inbox.',
            'expires_minutes': VERIFICATION_MINUTES,
        }
        if os.getenv('FLASK_DEBUG', 'true').lower() in ('1', 'true', 'yes') and not os.getenv('MAIL_SERVER'):
            payload['dev_code'] = code
        return jsonify(payload), 403
    login_user(user)
    return jsonify({'success': True, 'name': user.name})

@app.route('/logout')
def logout():
    session.pop('openai_api_key', None)
    session.pop('user_id', None)
    session.pop('user_name', None)
    return jsonify({'success': True})

@app.route('/history')
def history():
    blocked = verified_user_required()
    if blocked:
        return blocked
    screenings = Screening.query.filter_by(user_id=session['user_id']).order_by(Screening.created_at.desc()).limit(10).all()
    result = []
    for s in screenings:
        result.append({
            'id': s.id,
            'job_desc': s.job_desc[:100] + '...',
            'total_resumes': s.total_resumes,
            'created_at': s.created_at.strftime('%d %b %Y, %I:%M %p'),
            'results': json.loads(s.results),
            'notes': json.loads(s.notes) if s.notes else {}
        })
    return jsonify({'history': result})

@app.route('/save_note', methods=['POST'])
def save_note():
    blocked = verified_user_required()
    if blocked:
        return blocked
    data = request.get_json()
    screening = Screening.query.filter_by(id=data.get('screening_id'), user_id=session['user_id']).first()
    if not screening:
        return jsonify({'error': 'Not found'}), 404
    notes = json.loads(screening.notes) if screening.notes else {}
    notes[data.get('candidate')] = data.get('note','')
    screening.notes = json.dumps(notes)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/export_pdf', methods=['POST'])
def export_pdf():
    data = request.get_json()
    buf = generate_pdf_report(data.get('results',[]), data.get('job_desc',''))
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
                    download_name=f'screening_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf')

@app.route('/screen', methods=['POST'])
def screen():
    try:
        if not is_logged_in() and guest_attempts_used() >= GUEST_FREE_ATTEMPTS:
            return guest_limit_response()

        job_desc = request.form.get('job_desc','')
        files = request.files.getlist('resumes')
        if not job_desc or not files:
            return jsonify({'error': 'Missing required fields'}), 400

        resumes_dict = {}
        for f in files:
            if not f or not f.filename:
                continue
            if not f.filename.lower().endswith('.pdf'):
                continue
            text = extract_text(f)
            if text:
                resumes_dict[f.filename] = text

        if not resumes_dict:
            return jsonify({
                'error': 'No readable PDFs found. Upload one or more text-based PDF resumes.'
            }), 400

        use_ai = request.form.get('use_ai', '').lower() in ('1', 'true', 'yes', 'on')
        # Only use the key sent in this request — never .env or session (avoids surprise billing errors)
        api_key = (request.form.get('openai_api_key') or '').strip() if use_ai else ''
        warning = None
        mode = 'local'
        results = []

        if use_ai and api_key:
            try:
                raw = rank_resumes(job_desc, resumes_dict, api_key)
                results = parse_results(raw)
                if results:
                    mode = 'ai'
                else:
                    warning = 'AI returned no scores. Showing local matching instead.'
            except (openai.AuthenticationError, openai.RateLimitError, openai.APIError) as e:
                warning = friendly_openai_error(e) + ' Showing local matching instead (no API needed).'

        if not results:
            results = rank_resumes_local(job_desc, resumes_dict)
            mode = 'local'

        chart = generate_chart(results)

        screening_id = None
        user = get_current_user()
        if user and user.email_verified:
            screening = Screening(
                user_id=session['user_id'],
                job_desc=job_desc,
                results=json.dumps(results),
                total_resumes=len(resumes_dict),
                notes='{}'
            )
            db.session.add(screening)
            db.session.commit()
            screening_id = screening.id

        if not is_logged_in():
            record_guest_attempt()

        payload = {
            'results': results,
            'chart': chart,
            'screening_id': screening_id,
            'mode': mode,
            'attempts_remaining': guest_attempts_remaining(),
        }
        if warning:
            payload['warning'] = warning
        return jsonify(payload)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

with app.app_context():
    db.create_all()
    migrate_user_table()

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'true').lower() in ('1', 'true', 'yes')
    app.run(host='0.0.0.0', port=port, debug=debug)
