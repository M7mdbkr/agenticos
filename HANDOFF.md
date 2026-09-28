# Personal OS — Engineering Handoff

**Version:** 1.0
**Last updated:** 2026-09-06
**Author:** Mohammad J. Bakr · CE Student, Taif University

---

## What Was Built

A local-first personal agent operating system with 4 specialist agents, approval-gated external actions, n8n automation webhooks, per-agent browser isolation, and a warm cream-toned HTML/CSS/JS SPA.

**No cloud dependency.** No data leaves your machine unless you explicitly approve it.

---

## Project Map

```
personal-os/
├── personal_os.py          ← SQLite core — agents, messages, actions, audit
├── server.py               ← ThreadingHTTPServer — REST API, RSS fetcher, n8n
├── index.html               ← SPA shell
├── static/
│   ├── styles.css           ← Design system (warm cream tones, serif headings)
│   └── app.js              ← Full SPA: nav, chat, models, approvals, n8n, audit
├── docs/
│   ├── PROMPTS.md           ← System prompts for all 4 agents
│   ├── NOTION-DESIGN.md    ← 10 ready-to-paste Notion page templates
│   ├── GITHUB-SETUP.md     ← GitHub init, CI, branch strategy
│   └── ENGINEERING-REPORT.md ← Architecture, threat model, data model
├── samples/
│   └── n8n-workflow-telegram-notify.json  ← Import into n8n
└── .github/workflows/ci.yml ← GitHub Actions CI
```

**Git-ignored (never commit):**
- `data/` — SQLite database
- `uploads/` — uploaded files
- `browser-profiles/` — per-agent Chrome profiles
- `*.db*` — SQLite WAL/SHM files

---

## How to Run

```bash
cd ~/Desktop/Personal-OS
python3 server.py --host 127.0.0.1 --port 8765
# → http://127.0.0.1:8765
```

**With Hermes (smarter agents, safe toolset):**
```bash
PERSONAL_OS_ENABLE_HERMES=1 python3 server.py --enable-hermes
```

**Server starts in < 1 second.** No dependencies to install (stdlib only, Python 3.11+).

---

## Architecture Decisions

| Decision | Rationale |
|---|---|
| SQLite + file storage | No DB server process; portable; git-ignorable |
| ThreadingHTTPServer | Handles concurrent requests; one process |
| No auth layer | localhost-only; gate is the approval button |
| Offline fallback | Agents always respond; model is optional |
| n8n as separate process | n8n manages its own credentials and workflows |
| Per-agent Chrome profiles | Session isolation without browser automation complexity |
| SHA-256 audit chain | Corrections create new events; history is append-only |

---

## n8n Setup (5 minutes)

1. `n8n start` → http://localhost:5678
2. Import `samples/n8n-workflow-telegram-notify.json`
3. Activate the workflow; copy the webhook URL
4. Personal OS → **⇔ n8n automation** page → **＋ Add webhook**
5. Paste URL → Save → **Test** button confirms delivery

On every approval click, n8n receives:
```json
{
  "agent": "job",
  "action_type": "submit_application",
  "payload": { "company": "3M Corp", "role": "CE Engineer" },
  "digest": "a1b2c3..."
}
```

---

## GitHub Setup (5 minutes)

```bash
cd ~/Desktop/Personal-OS
git init
git add .
git commit -m "feat: initial Personal OS"
git remote add origin https://github.com/mohammadjbakr/personal-os.git
git branch -M main
git push -u origin main
```

CI runs automatically on every push. See `docs/GITHUB-SETUP.md`.

---

## Notion Setup (15 minutes)

Open `docs/NOTION-DESIGN.md` and copy each section into a new Notion page.
Key pages to create:
1. **Home / Dashboard** — quick stats, goals, agent status
2. **Job Applications** — database with Status, Source, Contact, Follow-up
3. **CV & Cover Letters** — template + tailoring guide
4. **Skills Inventory** — database tracking proficiency + evidence
5. **Target Companies** — research database
6. **Weekly Review** — every Sunday
7. **Learning Roadmap** — 0–12 month plan
8. **Tech Watch** — RSS reading list
9. **n8n / Automation Log** — webhook status + test history
10. **Personal OS / Documentation** — links to this repo

---

## Key Limitations

| Limitation | Workaround |
|---|---|
| No automatic LinkedIn apply | Open agent browser → manual apply → record in Job Tracker |
| Email only in Job Hunter | Job Hunter reads/sends via IMAP/SMTP app password (`docs/JOB-HUNTER.md`); other agents still draft only |
| n8n runs separately | n8n manages its own credential store |
| Browser profiles not sandboxed | Don't log into high-value accounts in agent browsers |
| No mobile UI | Designed for desktop (1024px+); works on tablet |

---

## Per-Agent Model Switching

Every agent has its own provider + model, changeable at any time:

| Agent | Default Provider | Default Model | Free Only |
|---|---|---|---|
| CEO | `offline` | `deterministic` | ✗ |
| Job | `ollama` | `qwen3:8b` | ✓ |
| Dad | `offline` | `deterministic` | ✗ |
| Tech News | `offline` | `deterministic` | ✗ |

Open **◌ Models** page to switch any agent to: `openrouter`, `anthropic`, `nous`, `openai-codex`, or keep `ollama` with a different model.

---

## Safety Invariants

1. **Every external action** — submit_application, send_email, deploy_source_change, account_change — creates a pending approval card.
2. **Nothing fires** without an explicit Approve click in the Approvals page.
3. **No credentials stored** in SQLite. Browser cookies stay in Chrome profiles. OAuth tokens go in Hermes credential store.
4. **Audit log is append-only.** Corrections add new events; hash chain is SHA-256.
5. **Free-only policy** per agent prevents accidental paid model usage.

---

## Known Issues

- `tech-news` agent workspace not yet in the nav group (planned for next release)
- Agent browser opens `about:blank` if no URL entered
- RSS fetch is offline-only; a configured model can add summarization

---

## What to Do Next

1. ☐ Run `python3 server.py` and open the app — verify it loads
2. ☐ Create GitHub repo and push
3. ☐ Set up n8n and add a Telegram webhook
4. ☐ Create Notion pages from `docs/NOTION-DESIGN.md`
5. ☐ Add 3 job sources to the Job Sources page
6. ☐ Switch the Job Agent model if Ollama is installed
7. ☐ Open the CEO workspace and send a test message
