# AI Resume Screener

Upload multiple PDF resumes and a job description — get ranked candidates with match scores, charts, and a downloadable PDF report.

Built by **Sai Jahnavi Madana** · NIT Warangal

## Features

- Multiple PDF resume upload
- **Local matching** (no API key required) — skill/keyword based ranking
- Optional **OpenAI AI mode** (bring your own API key)
- Guest trial: **2 free screenings**, then sign up required
- User accounts with **email verification** (6-digit code sent to inbox)
- Screening history and notes for verified users
- Clean black-and-white PDF export

## Tech stack

- Python · Flask · SQLite · ReportLab · Matplotlib
- HTML/CSS/JavaScript frontend

## Local setup

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/ai-resume-screener.git
cd ai-resume-screener
python -m venv venv
```

**Windows (PowerShell):**

```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**macOS / Linux:**

```bash
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Environment variables

```bash
copy .env.example .env
```

Edit `.env` and set a strong `SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Paste the output as `SECRET_KEY` in `.env`.

### Email verification (optional for local dev)

To send real verification emails, add Gmail SMTP settings to `.env`:

```env
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=your.email@gmail.com
MAIL_PASSWORD=your-16-char-app-password
MAIL_FROM=your.email@gmail.com
```

Gmail: Google Account → Security → 2-Step Verification → **App passwords** → create one for “Mail”.

**Without SMTP:** codes print in the terminal where `python app.py` runs (dev only).

> **Never commit `.env` to GitHub.** It is listed in `.gitignore`.

### 3. Run

```bash
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000)

## Deploy on Render (free tier)

1. Push this project to a **GitHub** repository (without `.env`).
2. Go to [render.com](https://render.com) → **New** → **Blueprint** (or **Web Service**).
3. Connect your GitHub repo.
4. If using **Blueprint**, Render reads `render.yaml` automatically.
5. If manual **Web Service**:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
   - **Health check path:** `/health`
6. Add environment variables in Render dashboard:
   - `SECRET_KEY` — generate a random string (required)
   - `FLASK_DEBUG` = `false`
   - `FLASK_ENV` = `production`
7. Deploy. Your live URL will look like `https://ai-resume-screener.onrender.com`.

### Notes for production

- SQLite data on Render’s free tier may reset on redeploy. For persistent data, add a free PostgreSQL database on Render and set `DATABASE_URL` in environment variables.
- OpenAI is optional; most users can use local matching without any API key.

## Project structure

```
ai-resume-screener/
├── app.py              # Flask backend
├── templates/
│   └── index.html      # Frontend UI
├── requirements.txt
├── Procfile            # For Render / Railway / Heroku
├── render.yaml         # Render Blueprint
├── .env.example        # Copy to .env locally
└── README.md
```

## Security checklist before GitHub push

- [ ] `.env` is **not** in the repo (only `.env.example`)
- [ ] `SECRET_KEY` is set in `.env` locally and in Render dashboard for production
- [ ] No real API keys in committed files

## License

MIT — free to use for learning and portfolio projects.
