# Job Hunter — the email-connected job agent

Job Hunter runs on your laptop and works for you around the clock:

- **Finds jobs on many sites.** LinkedIn (public search, no login), Remotive, RemoteOK, Jobicy,
  Himalayas, Arbeitnow, We Work Remotely, Greenhouse/Lever company career pages you list, any RSS
  feed, and — with a free API key — **JSearch** or **SerpAPI**, which read *Google for Jobs*
  (Indeed, Bayt, Glassdoor, LinkedIn, company sites and local boards together).
- **Reads your job-alert emails.** Alerts from LinkedIn, Indeed, Bayt, Glassdoor, Naukrigulf,
  GulfTalent, Wuzzuf… become new leads automatically.
- **Scores every posting** against your roles, skills, locations and level, and explains why
  (“title matches ‘IT support’ · skills: networking, linux · in Jeddah · entry-level friendly”).
- **Emails you the best new matches**, a daily report, and an alert the moment an employer replies.
- **Answers every email you send it.** Reply to any of its emails (or email it with subject
  `Jobs`) — `apply 1`, `skip 2 3`, `search data analyst in Riyadh`, `status`, or a plain question.
- **Tracks replies.** Employer emails are matched to your applications and classified as
  interview / assessment / offer / rejection; follow-ups are suggested after 7 days.
- **Uses your laptop.** Opens job pages in its own Chrome profile, attaches your CV from disk,
  shows desktop notifications, and starts automatically when the laptop boots.
- **Also on Telegram:** send `/jobs status`, `/jobs apply 1`… from the chat you configure.

**Safety rule:** nothing is ever sent to an employer until you approve it with `send <id>` (email,
Telegram or the Send button). Emails to *you* are automatic.

---

## 1. Set it up (5 minutes)

Easiest — one command that installs the card reader, asks your details, imports your CV, sends a test
email, runs the first search, installs the background service and checks everything:

```bash
bash scripts/install-jobhunter.sh
```

Anytime something seems off: `python3 -m jobhunter doctor` (or Settings → 🩺 Check everything) checks
email, every job site, the writing brain, the card reader and the service, and tells you the fix.

Or step by step:

```bash
cd ~/Desktop/Personal-OS          # this repository
python3 -m jobhunter setup        # asks for roles, skills, locations, CV and your email
python3 -m jobhunter once         # first search + inbox check
```

Or open **http://127.0.0.1:8765/#hunter** (run `python3 server.py`) → **Settings** tab.

### Email (Gmail)

1. Turn on 2-Step Verification: <https://myaccount.google.com/security>
2. Create an App Password: <https://myaccount.google.com/apppasswords> → copy the 16 letters.
3. Paste it in `setup` or in **Job Hunter → Settings → Email connection → Connect & test**.

Outlook/Hotmail, Yahoo and iCloud work the same way (use their app passwords). Other providers:
fill in the IMAP/SMTP servers under “Other providers”.

Two ways to use your mailbox:

| Mode | How | Commands |
|---|---|---|
| **Your own Gmail** (simplest) | Agent reads/sends as you | Reply to its emails, or email yourself with subject `Jobs` |
| **Dedicated agent mailbox** (e.g. `mohammad.jobhunter@gmail.com`) | Put your personal address in “Send updates to” | Anything you send to the agent mailbox is a command |

The agent opens the inbox **read-only** and never marks mail as read. For unrelated mail it stores
only the message id (so it isn't processed twice) — no subject, sender or content.

### More job sites (optional API keys in `.env`)

| Key | Get it at | Adds |
|---|---|---|
| `RAPIDAPI_KEY` | <https://rapidapi.com> → search “JSearch” (free tier) | Google for Jobs: Indeed, Bayt, Glassdoor, LinkedIn, company sites |
| `SERPAPI_KEY` | <https://serpapi.com> (free tier) | Google for Jobs |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `ADZUNA_COUNTRY` | <https://developer.adzuna.com> | UK/US/EU/India/… boards |

Keyed sources run at most once a day (a few calls each) so free quotas last the month.
Add company career boards in Settings (Greenhouse/Lever slugs, e.g. `careem`) and any RSS feed.
RSS entries on the **Job sources** page are picked up too.

## 2. Keep it running

- **Inside AgenticOS:** Job Hunter page → **▶ Start agent**. It auto-starts with `server.py` from
  then on.
- **As a background service** (runs even when the web app is closed, starts at login):

  ```bash
  python3 -m jobhunter install-service     # macOS launchd / Linux systemd --user
  ```

  Stop it: `launchctl unload -w ~/Library/LaunchAgents/com.agenticos.jobhunter.plist` (macOS) or
  `systemctl --user disable --now jobhunter` (Linux). Logs: `data/jobhunter/service.log`.

Only one scheduler runs at a time (a lock file prevents double emails). The web page shows
“Running as background service” when the service is active; buttons and commands still work.

Default rhythm (change in Settings): search every 3 h, inbox every 10 min, daily report at 09:00,
follow-up suggestion after 7 days.

## Dashboard

`python3 -m jobhunter dashboard` opens **http://127.0.0.1:8765/dashboard** — status, jobs with Prepare /
Send / Skip / "I applied" buttons, drafts waiting for your OK, applications, business cards, company sites,
settings, email connection and a health check. The background service runs the dashboard too, so the link
works whenever the laptop is on.

## Tidy inbox (Gmail)

Every inbox check files mail into Gmail labels: **Job Hunter/Employer replies** and **/Recruiters** stay in the
Inbox; **/Job alerts**, **/Applications** (confirmations), **/Commands** and **/Low priority** (ads, newsletters,
LinkedIn invitations) are moved out of the Inbox — nothing is deleted. Personal mail is left alone.
Tidy what is already there: `python3 -m jobhunter organize --days 30` (or 🧹 Tidy inbox). Turn it off in Settings.

## 3. Talk to it

Reply to any Job Hunter email (one command per line), use the **Ask** tab, `python3 -m jobhunter ask "…"`,
or Telegram `/jobs …`.

```
jobs                       your best open matches (numbered)
search network engineer in Riyadh
details 2                  full description
apply 1                    tailored application → you review it
send 7K2QX                 approve: send the prepared email (application / follow-up / reply)
cancel 7K2QX               throw the draft away
applied 7K2QX              you applied on the website → it tracks it and follows up
reply 7K2QX I'm free Tuesday 10am   drafts an answer in the employer's email thread
followup 7K2QX             polite follow-up draft
skip 3 4                   hide jobs
interview|offer|rejected 7K2QX
open 7K2QX                 open the job page in your laptop's browser
track https://…            add a job you found yourself
add role data analyst · remove skill php · add location Dammam · add exclude sales
set min score 60 · set level entry
status · run · pause · resume · help
```

Numbers (`apply 1`) refer to the list in the email you are replying to. Anything that isn't a
command is answered as a question — with a writing brain (Settings → Ollama / Claude Code /
Codex) the answers and cover letters are written by that model; without one, clean templates are
used. Cover letters only use the facts in your profile; job text is treated as data, not instructions.

## 4. How applications work

- **Job lists an email address** (common in Saudi LinkedIn/Bayt posts): `apply` prepares the
  email with your CV attached → you check it → `send <id>` sends it from your mailbox (a copy is
  BCC'd to you when using a dedicated mailbox). Employer replies land in the same thread and are
  tracked.
- **Website application** (most postings): `apply` opens the page on your laptop and gives you a
  tailored cover letter to paste. After submitting, `applied <id>` (or the “I applied” button)
  starts tracking. ATS emails (“Thank you for applying to Acme”, “Unfortunately…”) are matched by
  company name.

Form-filling on websites is deliberately not automated: sites use CAPTCHAs, LinkedIn forbids
automation (accounts get restricted), and a human glance before each application avoids mistakes.

## 5. Company websites, business cards and your master CV

**Company websites.** Send any link — `add company https://company.com` (email/Telegram/Ask), or
Job Hunter → *Contacts & companies* → Watch. It finds the careers page, detects Greenhouse / Lever /
Ashby / Workable / SmartRecruiters boards and reads every open role on each search. Portals that
only work in a browser (SAP SuccessFactors, Oracle, Workday, Taleo, Jadarat) are flagged so you
visit them yourself.

**Business cards.** Photograph the card and send it: attach it to an email to the agent (subject
`كرت` or `card`, or no subject when you use a dedicated mailbox), send the photo to the Telegram
bot, use *📷 Photo of a card* in the app, or `python3 -m jobhunter card IMG_1234.jpg`. It reads the
card with a local vision model (`ollama pull llama3.2-vision`) or `tesseract`
(`brew install tesseract tesseract-lang`), saves the contact, watches the company website, and — if
the card has an email — prepares an application with a CV tailored to that company. As always,
nothing goes out until you reply `send <id>`. If the photo can't be read, type it:
`card Ahmed Ali, HR Manager, Acme, ahmed@acme.sa, 0551234567`.

**Master CV → a tailored CV per job.** Write everything true about you once (Job Hunter → *CV*, or
`python3 -m jobhunter cv import ATS-1.docx`). For every application the agent writes a Word file
that puts the projects, bullets and skills that match that job first, adds “Target role: …”, and
trims less relevant bullets — it never adds anything that isn't in your master CV. It is attached to
email applications automatically, downloadable from each job card (“CV for this job”), and
`cv <id>` gives you the file path for website uploads.

Arabic commands work too: `وظائف` · `ابحث مهندس شبكات في الرياض` · `قدم 1` · `ارسل 7K2QX` ·
`تخطى 2` · `قدمت 7K2QX` · `الحالة` · `كرت …` · `اضف شركة https://…`.

## 6. Files and privacy

| What | Where (git-ignored) |
|---|---|
| Jobs, drafts, mail log, activity | `data/jobhunter/jobhunter.db` |
| Profile (no secrets) | `data/jobhunter/profile.json` |
| Master CV, tailored CVs, cover letters | `data/jobhunter/master_cv.md`, `data/jobhunter/cv/tailored/`, `data/jobhunter/letters/` |
| Business-card photos | `data/jobhunter/cards/` |
| Mail password, API keys, bot token | `.env` (mode 600) |

Email commands are accepted only from your address(es) and only when the message passes the
provider's SPF/DKIM/DMARC checks, so a forged “From” can't control the agent.

## Troubleshooting

- **“IMAP login failed”** — use an App Password, not your normal password; if your Gmail settings
  still show an IMAP switch (Forwarding and POP/IMAP), make sure it is on.
- **LinkedIn “rate limited (HTTP 429)”** — it retries next cycle; lower the number of roles or
  raise “Search every”.
- **No emails from the agent** — Settings → “Send me a test email”; check Activity for errors.
- **Nothing matches** — look at a job's “Details”: the reasons show what cost points; lower
  “Email me jobs scoring at least”, add skills, or set level to `any`.
- Run the tests: `python3 -m unittest tests.test_jobhunter -v` (offline, no real mail is sent).
