# AgenticOS

A local-first personal agent operating system built around explicit consent, visible state, and replaceable model providers.

## What it demonstrates

- Specialist workspaces for CEO, job, email, and technology-news workflows
- An Inbox that triages incoming company replies offline and drafts an answer for review
- Approval cards before any external action
- SQLite state and a SHA-256 audit chain for operational events
- Optional Telegram and n8n integrations, including an n8n-driven email trigger
- Local context library, schedules, and page-agent interactions
- Loopback-only defaults for local development

## Stack

Python standard library · SQLite · vanilla HTML/CSS/JavaScript · optional Ollama, Telegram, and n8n

## Run locally

```bash
python3 server.py --host 127.0.0.1 --port 8765
open http://127.0.0.1:8765
```

Run `python3 -m py_compile server.py personal_os.py brains.py` and `node --check static/app.js` for quick checks. The full test suite is in `tests/`.

## Privacy

Runtime databases, uploads, browser profiles, vault notes, and environment files are intentionally excluded from this repository. Configure integrations locally; never commit tokens.
