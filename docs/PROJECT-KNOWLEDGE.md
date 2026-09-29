# Job Hunter — complete project knowledge

> One file that explains everything about Job Hunter: what it is, how it is built, how to run and use it,
> the rules it follows, and where it is going. Written so a person — or Claude in a Claude Project — can
> understand the whole project without reading the code first. Personal data (phone, grades, passwords)
> is deliberately **not** in this public file.

---

## 1. What it is

Job Hunter is an AI job-search agent that runs **locally** on the owner's own computer (a Mac now, a Windows PC
later). It is a Python program (standard library only — no packages to install) that lives in the AgenticOS
repository:

- Repository: `github.com/M7mdbkr/agenticos`
- Branch: `claude/nice-maxwell-h5u3gr`
- Package: `jobhunter/` · Dashboard: `static/dashboard.html` · Server: `server.py`
- Installed on the laptop at `~/agenticos`

It works without Claude. Claude (the assistant) built it and is used to change or fix it.

### What it does, in one list
1. **Finds jobs** on many sites every 3 hours.
2. **Scores** each job 0–100% against the owner's roles, skills, cities and level, and explains the score.
3. **Emails** the best new matches, a daily report, and an alert as soon as a company replies.
4. **Reads the inbox** every 10 minutes: answers emailed commands, tracks company replies, turns job-alert emails
   into jobs, flags recruiters.
5. **Tidies Gmail** with labels and moves ads/newsletters out of the Inbox (never deletes).
6. **Prepares applications**: a cover letter plus a CV tailored to the job, sent only after the owner approves.
7. **Reads business cards** from a photo and turns them into contacts + application drafts.
8. **Follows up**: suggests a follow-up after 7 days without a reply and drafts replies in the employer's thread.
9. **Dashboard** in the browser to watch and control everything.

---

## 2. Architecture

```
  YOU                         JOB HUNTER (your computer)                      THE WORLD
 ┌──────────┐ commands  ┌──────────────────────────────────┐ searches  ┌──────────────────────┐
 │ Email    │──────────▶│ Commander ─▶ Agent core           │──────────▶│ LinkedIn · Bayt ·    │
 │ Telegram │◀──────────│   Scheduler (3h search, 10m mail) │◀──────────│ boards · company     │
 │ Dashboard│ answers   │   SQLite store (jobs, drafts…)    │ postings  │ career pages         │
 │ CLI      │           │   Dashboard server :8765          │           └──────────────────────┘
 └──────────┘           └──────────────┬───────────────────┘  only after ┌──────────────────────┐
   📷 card photos ─────────────────────┘                        "send" ──▶│ Employers' inboxes   │
                                                                           └──────────────────────┘
```

### Roles inside the agent (one program, several jobs)

| Role | Responsibility | Module |
|---|---|---|
| Scout | Searches every enabled source (first 4 roles × first 3 cities) | `sources.py`, `companies.py` |
| Scorer | Explainable 0–100 match | `scoring.py` |
| Writer | Cover letters, follow-ups, replies, digests (templates or local/subscription AI) | `writer.py` |
| CV Tailor | Master CV → job-specific ATS `.docx` (reorder/trim only) | `cv.py` |
| Card Reader | Business-card photo → contact (Ollama vision / tesseract) | `cards.py` |
| Inbox Watcher | IMAP read, classify replies/alerts/recruiters, Gmail labels | `mailbox.py`, `inbox.py` |
| Commander | English + Arabic text commands | `commands.py` |
| Gatekeeper | Approval before any employer email; owner-only, SPF/DKIM-verified commands | `agent.py` |
| Scheduler | Runs due work every 20 s tick; single-instance lock | `agent.py` |
| Doctor | Live health check of every part with fixes | `doctor.py` |
| Store | SQLite: jobs, outbox drafts, mail log, contacts, runs, events | `store.py` |
| Notify | Telegram, desktop notifications, open pages in Chrome | `notify.py` |
| Config/Profile | `.env` secrets, mail presets, profile JSON validation | `config.py`, `profile.py` |

---

## 3. Connectors

| Connector | Purpose | Needs |
|---|---|---|
| Gmail IMAP + SMTP | Read/send mail, labels | Gmail **App Password** (needs 2-Step Verification) |
| Job sites (HTTP) | Find jobs | Internet; optional API keys |
| Ollama (local) | Read card photos (`llama3.2-vision`); optional writing brain | Ollama app |
| tesseract | Fallback card OCR | `brew install tesseract tesseract-lang` |
| Claude Code / Codex CLI | Optional writing brain via `brains.py` | Logged-in CLI |
| Telegram bot | `/jobs …` commands and card photos | Bot token + chat ID in settings |
| Chrome | Opens postings in the agent's own profile | Installed browser |
| launchd / systemd / Task Scheduler | Start with the computer | `install-service` |

---

## 4. Job sources

| Source | Covers | Key? |
|---|---|---|
| LinkedIn public guest search | All countries; the owner's account is never used | No |
| Bayt.com search pages | Saudi Arabia, UAE, Gulf | No |
| Remotive, RemoteOK, Jobicy, Himalayas, We Work Remotely, Arbeitnow | Remote jobs | No |
| Company websites | Finds the careers page; Greenhouse, Lever, Ashby, Workable, SmartRecruiters APIs; plain job links | No |
| Greenhouse / Lever boards by slug, any RSS feed | Specific companies / feeds | No |
| Job-alert emails | LinkedIn, Indeed, Bayt, Glassdoor, Naukrigulf, GulfTalent, Wuzzuf… | No |
| JSearch (RapidAPI) / SerpAPI | Google for Jobs: Indeed, Glassdoor, Bayt, company sites | Yes (free tiers; budgeted to once a day) |
| Adzuna | UK/US/EU/India… | Yes |

Browser-only portals (SAP SuccessFactors, Oracle, Workday, Taleo, Jadarat) are reported, not scraped.
Indeed is **not** scraped directly (the only way is impersonating its mobile app — against its terms).

### Scoring

| Signal | Points |
|---|---|
| Title contains a target role | +45 (all words +38, half +22, only in text +12) |
| Skills found in the posting | up to +30 |
| In a wanted city (regions expand: "Eastern Province" = Dammam, Khobar, Dhahran, Jubail…) | +20 |
| Remote & open to the region (only if remote is wanted) | +15 |
| Entry-level words (junior, graduate, trainee, Tamheer…) | +15 |
| Posted ≤ 3 days | +5 |
| Senior/Lead/Manager title for an entry-level profile | −40 |
| Asks for 3+ / 5+ years | −15 / −30 |
| Excluded word in title / outside cities with strict mode | blocked |
| Only "Saudi Arabia" with no city | neutral ("city not specified") |

Jobs below 20 are not stored; the email threshold (`min_score`) defaults to 50.

---

## 5. Business cards

Photo → (HEIC converted with `sips`) → Ollama `llama3.2-vision` JSON extraction, else tesseract OCR + regex, else
the owner types it (`card Ahmed Ali, HR Manager, Acme, ahmed@acme.sa, 0551234567`) → contact saved →
company website added to the watch list → if there is an email, an "open application" job is created and an
application draft with a tailored CV waits for `send`.

Ways to send a card: email to the agent with subject `card` (or a photo with no subject in a dedicated mailbox),
Telegram photo from the linked chat, dashboard upload, `python3 -m jobhunter card photo.jpg`.

---

## 6. Master CV and tailoring

The master CV is a text file (`data/jobhunter/master_cv.md`):

```
# Name
contact line
## Section
### Entry heading
- bullet
plain line
```

For each job, `cv.tailor()` weights keywords (job title ×3, matching profile skills ×3, frequent description
words ×1), then: sorts bullets by relevance (max 5 per entry), reorders and keeps the top 4 projects, puts the
job's skills first in skill lines, and adds "Target role: <title> at <company>". It never adds content. Output:
single-column `.docx` (no tables/images) that ATS systems parse well. Import an existing `.docx` with
`cv import`.

---

## 7. Email behaviour

- Reads INBOX **read-only** with `BODY.PEEK` (never marks as read), tracks UIDs, first run looks back 2 days.
- Command mail = from an owner address **and** (dedicated mailbox, or reply to an agent email, or subject starting
  with `Jobs`/`card`/`كرت`, or a photo attached), **and** passes SPF/DKIM/DMARC (first Authentication-Results header).
- Replies are threaded (`In-Reply-To`/`References`); numbered lists map to the email being replied to.
- Employer replies: matched by thread, then company name/domain; classified rejection → offer → interview →
  assessment → received.
- Unrelated mail: only its Message-ID is stored.

### Gmail labels

| Label | Content | Inbox |
|---|---|---|
| Job Hunter/Employer replies | Company answers | stays |
| Job Hunter/Recruiters | Recruiter outreach | stays |
| Job Hunter/From agent | Digests, reports | stays |
| Job Hunter/Job alerts | Alert emails (already ingested) | archived |
| Job Hunter/Applications | "Thank you for applying" | archived |
| Job Hunter/Commands | Emails the owner sent the agent | archived |
| Job Hunter/Low priority | Ads, newsletters, invitations | archived |

---

## 8. Commands

| Command | Effect |
|---|---|
| `status` / `الحالة` | Pipeline summary |
| `jobs [N]` / `وظائف` | Best open matches, numbered |
| `search <role> [in <city>]` / `ابحث … في …` | Search every site now |
| `details <id\|#>` | Full description |
| `apply <id\|#>` / `قدم 1` | Letter + tailored CV; email jobs → draft |
| `send <id>` / `ارسل <id>` | Approve and send the pending draft |
| `cancel <id>` | Discard the draft |
| `applied <id>` / `قدمت <id>` | Mark applied (website) → tracked + follow-up |
| `skip <id…>` / `تخطى` | Hide |
| `interview` / `offer` / `rejected <id>` | Set status |
| `reply <id> <text>` | Draft a reply in the employer's thread |
| `followup <id>` | Draft a follow-up |
| `open <id>` | Open the posting on the laptop |
| `track <url>` | Add a job you found |
| `card <details>` / `contacts` | Save / list contacts |
| `cv [<id>]` | Master CV status / tailored CV path |
| `add\|remove role\|skill\|location\|exclude\|company <value>` | Edit profile |
| `set min score N` · `set level entry` · `set remote on\|off` · `set strict on\|off` | Settings |
| `run` · `pause` · `resume` · `help` | Control |

Anything else is answered as a question (by the writing brain if configured).

### Terminal (inside `~/agenticos`)

| Command | Purpose |
|---|---|
| `bash scripts/install-jobhunter.sh` | One-command install (card reader, setup, CV import, test mail, first search, service, doctor) |
| `python3 -m jobhunter setup` | Interactive profile + email |
| `python3 -m jobhunter dashboard [--foreground]` | Open (and start) the dashboard |
| `python3 -m jobhunter once` / `run` | One cycle / run forever |
| `python3 -m jobhunter search "AI engineer" -l Riyadh` | Search now |
| `python3 -m jobhunter status` · `inbox` · `test-email` | Status / read mail / test mail |
| `python3 -m jobhunter organize --days 30` | Tidy existing Gmail |
| `python3 -m jobhunter card <photo\|text>` | Save business cards |
| `python3 -m jobhunter cv import\|show\|tailor` | Master CV |
| `python3 -m jobhunter doctor [--offline]` | Health check |
| `python3 -m jobhunter install-service [--dry-run]` | Start with the computer (runs the server + agent) |
| `git pull` | Get updates |

---

## 9. Dashboard

`http://127.0.0.1:8765/dashboard` (also reached from AgenticOS → Job hunter). Tabs: **Jobs · Waiting for OK ·
My applications · Cards & companies · CV · Settings · Ask · Activity**. Top buttons: Start/Stop, Search now,
Check email, Tidy inbox, Health check. Shows plain-English alerts when email is not connected, the agent is
stopped, or settings are wrong. Localhost only; cross-origin requests are rejected.

### HTTP API (`/api/jobhunter/…`, localhost only)

`GET status · profile · jobs[?status,q,min_score,limit,order] · jobs/<id> · jobs/<id>/cv (docx) · drafts ·
activity · contacts · cv/master` — `POST profile · ask · search · run · inbox · organize · start · stop · email ·
email/test · doctor · cards (raw image) · cv (raw file) · cv/import · cv/master · contacts · jobs (track url) ·
jobs/<id>/<apply|send|cancel|applied|followup|open|skip|save|interview|assessment|offer|rejected|close|reopen|reply> ·
drafts/<id>`

---

## 10. Configuration

### Secrets (`~/agenticos/.env`, git-ignored, mode 600)

| Variable | Meaning |
|---|---|
| `JOBHUNTER_EMAIL` / `JOBHUNTER_EMAIL_PASSWORD` | Mailbox + App Password |
| `JOBHUNTER_IMAP_HOST` / `JOBHUNTER_SMTP_HOST` / `JOBHUNTER_SMTP_PORT` | Only for non-Gmail/Outlook/Yahoo/iCloud |
| `JOBHUNTER_OWNER_EMAIL` | Extra owner addresses |
| `RAPIDAPI_KEY` · `SERPAPI_KEY` · `ADZUNA_APP_ID` · `ADZUNA_APP_KEY` · `ADZUNA_COUNTRY` | Optional sources |
| `TELEGRAM_BOT_TOKEN` | Telegram |
| `JOBHUNTER_AUTOSTART=1` · `JOBHUNTER_DATA_DIR` · `JOBHUNTER_TRUST_UNVERIFIED=1` | Advanced |

### Profile (`data/jobhunter/profile.json`) — main keys
`name, phone, headline, summary, cv_path, roles, skills, locations, exclude, level (entry|mid|senior|any),
remote_ok, strict_location, min_score, sources{}, company_sites, greenhouse_boards, lever_boards, rss_feeds,
owner_emails, telegram_chat_id, notify_email|telegram|desktop, notify_when_empty, daily_summary_hour,
digest_max, search_every_minutes, inbox_every_minutes, follow_up_days, paused, autostart,
open_browser_on_apply, organize_inbox, brain (none|ollama|claude-code|codex-cli), brain_model, vision_model`

### Data files (`data/jobhunter/`, git-ignored)
`jobhunter.db` (SQLite) · `profile.json` · `master_cv.md` · `cv/` (uploaded + `tailored/`) · `letters/` ·
`cards/` · `scheduler.lock` · `server.log` / `service.log`

---

## 11. Safety rules (never broken)

1. Nothing reaches an employer until the owner approves (`send <id>` or the Send button).
2. Commands only from owner addresses that pass SPF/DKIM/DMARC; agent-sent mail is recognised and ignored.
3. CV tailoring never invents facts; cover letters use only profile facts; job text is treated as data.
4. LinkedIn: public search only; the owner's account is never automated.
5. Secrets only in `.env`; nothing personal in git.
6. Inbox tidying only labels/archives — never deletes.
7. Localhost-only server with Host/Origin checks.
8. Only permissive licences (MIT/Apache/BSD); standard library only.

---

## 12. Setup and daily use

**One time:** enable Google 2-Step Verification → create an App Password → run the installer (or the one-command
setup) → paste the App Password → `python3 -m jobhunter dashboard` → Health check.

**Daily:** read the morning report → reply `apply 1` → approve drafts (Waiting for OK) → for website jobs, open the
posting, upload "CV for this job", press "I applied" → photograph business cards → answer company replies with
`reply <id> …`.

**Move to a PC:** clone the repo on the PC, copy `data/jobhunter/` and `.env`, run `install-service`
(Windows: the command prints a Task Scheduler line), stop the Mac service.

---

## 13. Troubleshooting

| Symptom | Fix |
|---|---|
| "App passwords not available" | Turn on 2-Step Verification on that Google account |
| `AUTHENTICATIONFAILED` | Wrong/old App Password or wrong Google account — create a new one |
| Dashboard doesn't open | `python3 -m jobhunter dashboard` (explains port/crash) or `--foreground` |
| No jobs | Health check; lower min score; more roles; check cities |
| LinkedIn 429 | Rate-limited; retried next cycle |
| Card not read | Start Ollama / install tesseract / type the card |
| Anything | `python3 -m jobhunter doctor` |

---

## 14. Testing

`python3 -m unittest discover tests` — 73 offline tests (no network, fake mailbox): scoring, every source
parser, store, commands (EN/AR), inbox flows, spoofing, threading, cards, CV tailoring/docx, company sites, Gmail
labels, doctor, HTTP API, multipart upload. Works on Python 3.9–3.13.

---

## 15. Roadmap — Alfred OS

Job Hunter is planned to become the tools of the **Job Agent** inside **Alfred OS** (Hermes Agent as the only
engine, code in `~/Downloads/alfred-os`, approvals through Hermes, facts from `claims.yaml`, drafts to Gmail Drafts
instead of sending). The step-by-step handoff is `docs/ANTIGRAVITY-HANDOFF.md`.

## 16. Related documents
`docs/JOB-HUNTER.md` (user guide) · `docs/ANTIGRAVITY-HANDOFF.md` (Alfred merge) · `README.md` · the PDF
"Job Hunter — project guide".
