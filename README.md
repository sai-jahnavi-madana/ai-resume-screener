# AI Resume Screener

An intelligent resume screening web application that ranks candidates against job descriptions using skill matching and optional AI analysis.

**Built by [Sai Jahnavi Madana](https://www.linkedin.com/in/sai-jahnavi-madana-36a491341/) · NIT Warangal**

🔗 **Live Demo:** https://ai-resume-screener-zdls.onrender.com/

---

## Overview

AI Resume Screener helps recruiters and hiring managers quickly rank candidates by analyzing resumes against job descriptions. It works instantly without any API key using local skill matching, with optional OpenAI GPT-4o integration for deeper AI analysis.

---

## Features

- 📄 Upload multiple PDF resumes and rank instantly
- 🤖 Optional AI analysis using OpenAI GPT-4o
- 🔐 User authentication with email verification
- 📊 Score visualization chart
- 📋 Screening history saved per user
- 📝 Candidate notes per screening
- 📥 PDF report download
- 🌙 Dark and light mode
- 🎯 Job description templates
- 👤 Guest trial — 2 free screenings before sign up

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, Flask |
| Database | SQLite (local) / PostgreSQL (production) |
| AI | OpenAI GPT-4o (optional) |
| PDF Processing | PyPDF2, ReportLab |
| Charts | Matplotlib |
| Frontend | HTML, CSS, JavaScript |
| Deployment | Render |

---

## Screenshots

> Add screenshots here after taking them!

---

## Setup & Installation

**1. Clone the repo**
```bash
git clone https://github.com/sai-jahnavi-madana/ai-resume-screener.git
cd ai-resume-screener
```

**2. Install dependencies**
```bash
pip install flask flask-sqlalchemy werkzeug python-dotenv openai pypdf2 reportlab matplotlib

SECRET_KEY=your-secret-key
OPENAI_API_KEY=sk-...
FLASK_DEBUG=true

**4. Run**
```bash
python app.py
```

Open `http://localhost:5000`

---

## How It Works

1. User uploads PDF resumes
2. User pastes job description
3. App extracts text from PDFs
4. Local skill matching ranks candidates instantly
5. Optional OpenAI GPT-4o for deeper analysis
6. Results shown with score chart and PDF report

---

## Data Storage

| Data | Where Stored |
|---|---|
| User accounts | SQLite / PostgreSQL database |
| Screening history | Database per user |
| Candidate notes | Database per screening |
| PDF reports | Generated on the fly |
| API key | Browser only, never on server |

---

## Deployment

Deployed on **Render** — [Live Demo](https://ai-resume-screener-zdls.onrender.com/)

---

## About

Built by **Sai Jahnavi Madana**
- 🎓 B.Tech CSE @ Adikavi Nannaya University (2027)
- 🔬 AI/ML Research Intern @ NIT Warangal
- 💼 [LinkedIn](https://www.linkedin.com/in/sai-jahnavi-madana-36a491341/)
- 💻 [GitHub](https://github.com/sai-jahnavi-madana)
```

**3. Create `.env` file**
