# Handoff: merge Job Hunter into Alfred OS (for the Antigravity agent)

Paste everything below the line into the Antigravity agent, opened on `~/Downloads/alfred-os`.

---

You are working on my Mac inside `~/Downloads/alfred-os` (Alfred OS). Your job: turn the existing
**Job Hunter** code into tools for the **Job Agent** Hermes profile, following the Alfred OS rules
below. Work step by step, run tests after each step, and stop to ask me before anything irreversible.

## Rules from my Alfred OS plan (never break these)
1. **Hermes Agent is the only engine.** Add code as the `alfred` plugin / profile config. Never edit Hermes' own source.
2. **`~/Downloads/alfred-os` is the only place for new code.** `~/Alfred` and `~/Alfred AI` are frozen (reference only).
3. **Approvals:** reading runs freely; deleting/installing asks; **sending, applying and paying only with my explicit approval** (use Hermes approvals).
4. **Email:** only the job mailbox `mohammadbakerwork@gmail.com`, **read + drafts** (save drafts into Gmail's Drafts folder; I press Send myself). My personal email is never touched.
5. **Truth:** facts about me come only from `claims.yaml`, which is **never committed to git**. Never invent experience, degrees or certificates.
6. **LinkedIn:** assistance only — public job search is fine, **no automation of my LinkedIn account**.
7. **Licences:** MIT / Apache / BSD only. No GPL/AGPL/LGPL, no Elastic licence. (Job Hunter uses only the Python standard library.)
8. **Name:** display name is **"Mohammed Bakr"** (with an e). The email and LinkedIn slug `mohammad1baker` keep their spelling.
9. Agents don't talk to each other; everything goes through Alfred via Kanban.

## Step 0 — check the brain (I may need to act)
The Job Agent failed with `request (8868 tokens) exceeds the available context size (4096 tokens)`.
Ask me to set **Ollama app → Settings → Context length → 64k** and restart Ollama, then verify with a test
prompt through the `jobagent` profile. Don't continue until it answers.

## Step 1 — get and understand Job Hunter
```bash
git clone -b claude/nice-maxwell-h5u3gr https://github.com/M7mdbkr/agenticos.git /tmp/agenticos
cd /tmp/agenticos && python3 -m unittest tests.test_jobhunter
```
Read `docs/JOB-HUNTER.md` and `jobhunter/`. Modules:
`sources.py` (LinkedIn public search, Bayt, Remotive, RemoteOK, Jobicy, Himalayas, Arbeitnow, We Work Remotely,
Greenhouse/Lever, RSS, optional JSearch/SerpAPI/Adzuna) · `companies.py` (watch company career sites) ·
`scoring.py` (explainable 0–100 match) · `store.py` (SQLite) · `inbox.py` (classify employer replies,
job-alert emails) · `mailbox.py` (IMAP/SMTP) · `cards.py` (business-card photo → contact via Ollama vision/tesseract) ·
`cv.py` (master CV → tailored ATS .docx, reorder/trim only) · `writer.py` (letters) · `commands.py` (Arabic/English commands) ·
`doctor.py` (health check). `agent.py` has its own scheduler and `server.py` a web UI — **don't port those**.

## Step 2 — port into alfred-os
First read how the existing `alfred` plugin registers tools and where profiles live (`~/.hermes/profiles/jobagent/`).
Then create a package inside alfred-os (e.g. `alfred_jobs/`) with the reusable modules, and:
- **Remove** Job Hunter's own scheduler, background service, web UI and SMTP sending.
- **Drafts instead of sending:** replace `send` with "save to Gmail Drafts" (IMAP `APPEND` to `[Gmail]/Drafts`,
  with the tailored CV attached). Any real send must go through a Hermes approval.
- **claims.yaml adapter:** read `claims.yaml` (inspect its schema) and build the master CV structure used by
  `cv.py` from it, instead of `master_cv.md`. Keep the rule: tailoring only reorders/trims, never adds facts.
- Keep data (SQLite, card photos, tailored CVs) in a git-ignored data folder; secrets only in the profile's env/.env.

## Step 3 — expose tools to the Job Agent
Register tools following the plugin's conventions, e.g.:
`jobs_search(query, location)`, `jobs_list(status)`, `job_details(id)`, `job_prepare_application(id)` (letter + tailored CV → Gmail draft, needs approval),
`job_mark(id, status)`, `inbox_check()`, `card_read(image_path)` → contact + draft if it has an email,
`company_watch(url)`, `cv_tailor(id)` → .docx path, `jobs_doctor()`.
Update `~/.hermes/profiles/jobagent/SOUL.md` / `config.yaml` so the Job Agent knows the tools and the rules above.

## Step 4 — schedule through Hermes (not a separate service)
Hermes cron for the `jobagent` profile: job search every 3 hours, inbox check every 10 minutes.
Results go to a Kanban card for Alfred; the Briefing agent reads the job store for the morning summary.
Business-card photos I send to Alfred (Telegram/app) go to `card_read`.

## Step 5 — tests and proof
Port `tests/test_jobhunter.py` (adapt to drafts instead of sending, claims.yaml instead of master_cv.md).
Run the plugin's existing tests (23 on Hermes 0.21.1) + the new ones — all must pass.
Then run `jobs_doctor()` live and show me: which job sites answer, email login, card reader, brain.
Do a real search for "IT support" in Saudi Arabia and show me the top 5 with scores.

## Step 6 — report
Tell me in short Arabic: what works, what failed and why, what I must do (with exact clicks/commands),
and commit to alfred-os git with a clear message (never commit claims.yaml, .env or data).
