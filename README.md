# AgenticOS

A local-first personal agent operating system built around explicit consent, visible state, and replaceable model providers.

## What it demonstrates

- Specialist workspaces for CEO, job, email, and technology-news workflows
- **Job Hunter** — an email-connected job agent that searches LinkedIn, remote boards, company career pages and job-alert emails, emails you ranked matches, answers your email/Telegram commands, tracks employer replies and drafts applications you approve with one word ([docs/JOB-HUNTER.md](docs/JOB-HUNTER.md) · everything in one file: [docs/PROJECT-KNOWLEDGE.md](docs/PROJECT-KNOWLEDGE.md))
- Approval cards before any external action
- SQLite state and a SHA-256 audit chain for operational events
- Optional Telegram and n8n integrations
- Local context library, schedules, and page-agent interactions
- Loopback-only defaults for local development

## Stack

Python standard library · SQLite · vanilla HTML/CSS/JavaScript · optional Ollama, Telegram, and n8n

## Run locally

```bash
python3 server.py --host 127.0.0.1 --port 8765
open http://127.0.0.1:8765
```

Job Hunter on its own (no web app): `python3 -m jobhunter setup`, then `python3 -m jobhunter install-service` to keep it running on your laptop.

Run `python3 -m py_compile server.py personal_os.py brains.py` and `node --check static/app.js` for quick checks. The full test suite is in `tests/`.

## Privacy

Runtime databases, uploads, browser profiles, vault notes, and environment files are intentionally excluded from this repository. Configure integrations locally; never commit tokens.
