# Auto Job Hunter (India + Remote, 100% Free)

A fully-automated job hunting bot that:

1. Scrapes fresh software / SDE jobs from LinkedIn, Naukri, Indeed, Wellfound, RemoteOK, and big-MNC career pages every 1 hour.
2. Filters them for your level (1–3 yrs, 15 LPA+, India + remote).
3. Uses Google Gemini (free tier) to **tailor your resume** for each job using Jake's LaTeX template.
4. Compiles the LaTeX into a PDF.
5. Sends jobs to you on **Telegram** with `Apply` / `Skip` buttons + the tailored PDF attached.
6. When you tap **Apply**, the bot opens the application page for you (and tries auto-submit on supported ATS like Greenhouse / Lever / Ashby).

Everything runs on **GitHub Actions + Cloudflare Workers free tier** — no credit card, no server bills.

---

## Architecture (one-glance)

```
              ┌─────────────────────────────┐
              │  GitHub Actions (cron 1hr)  │
              │  scrape → filter → tailor   │
              │  → compile PDF → push to TG │
              └──────────────┬──────────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │   Telegram chat  │
                    │  (Apply / Skip)  │
                    └────────┬─────────┘
                             │ button click
                             ▼
            ┌────────────────────────────────┐
            │  Cloudflare Worker (free)      │
            │  receives callback,            │
            │  opens apply URL,              │
            │  marks as applied in DB        │
            └────────────────────────────────┘
```

Storage: a small SQLite file (`db/jobs.db`) committed back to the repo by the GitHub Action so we don't re-send the same job twice.

---

## SETUP — step by step (non-technical friendly)

You will do this **once**, then it runs forever for free. Total time: ~30 minutes.

### Step 1 — Get your free API keys & accounts

You said you already have these — great. Here is exactly what you need to grab from each:

| Service | What to copy | Where |
|---|---|---|
| Telegram | **Bot token** | Open Telegram, message `@BotFather`, send `/newbot`, follow prompts. Copy the token (looks like `12345:ABC...`). |
| Telegram | **Your chat ID** | Message `@userinfobot`. It replies with your numeric chat ID. |
| Google AI | **Gemini API key** | https://aistudio.google.com/apikey → "Create API key". Free, 15 req/min. |
| GitHub | nothing to copy | Just need an account. |
| Cloudflare | nothing to copy | Sign up at cloudflare.com (free). |

### Step 2 — Fork this project to your GitHub

1. Push this whole `job-hunter/` folder to a new repo on your GitHub (call it whatever, e.g. `job-hunter`).
2. Make it **private** (your resume info will be in there).

### Step 3 — Add your secrets in GitHub

In your repo on GitHub:

`Settings` → `Secrets and variables` → `Actions` → `New repository secret`

Add these one by one:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | from @BotFather |
| `TELEGRAM_CHAT_ID` | from @userinfobot |
| `GEMINI_API_KEY` | from aistudio.google.com |
| `WORKER_SECRET` | any random string (e.g. paste from `openssl rand -hex 16`) — used so only your worker can talk to your bot |

Optional **repository variable** (Settings → Secrets and variables → Actions → **Variables** tab):

| Name | Value |
|---|---|
| `AUTO_SUBMIT` | `true` to actually click the submit button after auto-fill on Greenhouse/Lever/Ashby. Default `false` (you click submit yourself). Recommended to leave `false` until you've watched a few runs and trust it. |

### Step 4 — Fill in your resume data

Open `resume/master_resume.json` and put your real info in (name, email, work experience, projects, skills, etc.). This is the "source of truth" the AI uses to tailor each job.

Open `resume/preferences.yaml` and adjust filters if needed (default: 1–3 yrs, India + remote, 15 LPA min, all SDE/SWE roles).

### Step 5 — Deploy the Cloudflare Worker (handles Yes/No buttons)

The worker is what listens 24/7 for your button taps (GitHub Actions can't do that — it only runs on a schedule).

1. Install Wrangler (Cloudflare's CLI) — only needed once on your laptop:
   ```bash
   npm install -g wrangler
   wrangler login
   ```
2. From this folder:
   ```bash
   cd worker
   wrangler secret put TELEGRAM_BOT_TOKEN     # paste your bot token
   wrangler secret put WORKER_SECRET           # paste the same WORKER_SECRET as above
   wrangler secret put GITHUB_TOKEN            # a GitHub Personal Access Token w/ "repo" scope, used to update the DB
   wrangler secret put GITHUB_REPO             # e.g. "yourname/job-hunter"
   wrangler deploy
   ```
3. Wrangler prints a URL like `https://job-hunter.YOURNAME.workers.dev`. Copy it.
4. Tell Telegram to send button events to your worker:
   ```bash
   curl -F "url=https://job-hunter.YOURNAME.workers.dev/telegram" \
        https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook
   ```

### Step 6 — Turn on the GitHub Action

In your GitHub repo → `Actions` tab → enable workflows → the `Job Hunter Hourly` workflow will start running automatically every hour at :00.

You can also click `Run workflow` to test it immediately.

---

## What you'll get on Telegram

Every hour, up to 20 jobs/day will arrive looking like this:

```
🟢 Senior Backend Engineer — Razorpay
📍 Bangalore (Hybrid) · 💰 ₹28–40 LPA · 🗓 Posted 2h ago
🛠 Python, Go, PostgreSQL, AWS
📝 Build payment infrastructure handling 1B+ TXN/month...

[📄 Tailored Resume PDF attached]

[ ✅ Apply ]   [ ❌ Skip ]   [ 🔗 View JD ]
```

Tap **Apply** → bot opens the application page in your phone's browser, with your resume already on disk. For Greenhouse/Lever/Ashby ATS pages, the bot autofills name, email, phone, and uploads the PDF.

Tap **Skip** → bot remembers and never shows you that company/role again for 30 days.

---

## File map

```
job-hunter/
├─ README.md                       ← you are here
├─ requirements.txt                ← Python deps
├─ resume/
│  ├─ master_resume.json           ← YOUR DATA (edit this)
│  ├─ preferences.yaml             ← filters
│  └─ jakes_resume_template.tex    ← Jake's LaTeX template
├─ scrapers/
│  ├─ __init__.py
│  ├─ base.py                      ← Job dataclass + base scraper
│  ├─ linkedin.py
│  ├─ naukri.py
│  ├─ indeed.py
│  ├─ wellfound.py
│  ├─ remoteok.py
│  ├─ ats.py                       ← Greenhouse/Lever/Ashby (Google, MS, etc.)
│  └─ run_all.py                   ← orchestrator
├─ tailor/
│  ├─ gemini_tailor.py             ← AI rewrites bullets
│  └─ latex_builder.py             ← writes .tex file
├─ bot/
│  ├─ send_jobs.py                 ← pushes jobs to Telegram
│  └─ apply_helper.py              ← auto-fills Greenhouse/Lever forms
├─ worker/
│  ├─ wrangler.toml
│  └─ src/index.js                 ← Cloudflare Worker (button handler)
├─ db/
│  └─ jobs.db                      ← SQLite (auto-created)
└─ .github/workflows/
   └─ hourly.yml                   ← cron job
```

---

## Costs

| Component | Cost |
|---|---|
| GitHub Actions (2000 min/month free) | ₹0 — uses ~5 min/hr × 24 = 120 min/day = ~3600 min/mo. **Slightly over!** Use Step 7 below. |
| Cloudflare Workers (100k req/day free) | ₹0 |
| Gemini API (15 req/min free) | ₹0 |
| Telegram | ₹0 |
| **Total** | **₹0** |

### Step 7 — Stay inside GitHub free quota

The default workflow runs hourly = 120 min/day = ~3600 min/month, which exceeds the 2000 min/month free tier on private repos. Two fixes:

**Option A (easiest):** Make the repo **public** — GitHub Actions are unlimited on public repos. Put your resume JSON in a private gist and pull it via secret URL instead.

**Option B:** Reduce frequency to every 2 hours (`cron: "0 */2 * * *"` in `hourly.yml`) → 1800 min/month → fits free.

**Option C:** Run on Oracle Cloud free VM instead (covered in `worker/README.md`).

---

## Troubleshooting

- **No jobs arriving?** Run the workflow manually from `Actions` tab and check the logs. Most common issue: a scraper got blocked. Each scraper is independent — others keep working.
- **PDF not generating?** GitHub Action has a LaTeX install step; if it fails, check `Actions` logs for missing TeX packages.
- **Telegram buttons don't work?** Make sure you ran `setWebhook` in Step 5.4 with the right URL.

---

## Important honesty disclaimer

This tool **opens application pages and pre-fills standard ATS forms**. It does **not** bypass CAPTCHAs, log in to LinkedIn, or auto-submit on sites that explicitly forbid automation in their ToS. That's by design — to keep you safe from account bans. The "Apply" button gets you 80% of the way there; you tap submit.
