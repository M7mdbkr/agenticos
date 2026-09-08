# GitHub Setup — Personal OS

## One-Time Setup

```bash
cd ~/Desktop/Personal-OS

# Initialize git (already has .gitignore)
git init
git add .
git commit -m "feat: initial Personal OS — local-first agent OS

- personal_os.py: SQLite core, 4 agents, approval gate, n8n hooks
- server.py: ThreadingHTTPServer, all REST endpoints, RSS fetcher
- index.html + static/: warm cream-toned SPA, 4 agents, approvals, files
- docs/: prompts, notion design, engineering report, samples

Agents: CEO, Job, Dad's Email, Tech News
Safety: every external action requires explicit approval
Automation: n8n webhooks fire on approval decisions"

# Create the repo on GitHub first, then:
git remote add origin https://github.com/mohammadjbakr/personal-os.git
git branch -M main
git push -u origin main
```

## Recommended GitHub Settings

**Repository → Settings → General**
- Features → Issues: **Enabled** (for job tracker later)
- Features → Discussions: **Enabled** (optional)
- Pull Requests → ✅ Allow merge commits
- ✅ Auto-delete head branches

**Repository → Settings → Pages**
- Source: Deploy from `gh-pages` branch (or GitHub Actions)

**Repository → Settings → Secrets → Actions**
Add these if you want CI:
- `HERMES_API_KEY` — your Hermes API key
- `N8N_URL` — `http://localhost:5678` (for self-hosted runners)

## GitHub Actions CI (optional)

```yaml
# .github/workflows/test.yml
name: Test Personal OS

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Check Python syntax
        run: python3 -m py_compile server.py personal_os.py
      - name: Check JS syntax
        run: node --check static/app.js
      - name: Check HTML
        run: python3 -c "from html.parser import HTMLParser; HTMLParser().feed(open('index.html').read())"
```

## Branch Strategy

```
main          — stable, deployable
├── dev       — experimental features (new agents, pages)
├── n8n       — n8n workflow iteration
└── gh-pages  — GitHub Pages deploy (if using static hosting)
```

## Semantic Commits

```
feat:     new feature
fix:      bug fix
docs:     documentation only
refactor: code restructure without behaviour change
test:     adding tests
chore:    maintenance, deps, tooling
```

## Updating the Repo

```bash
# After any code change:
git add -u
git commit -m "fix: n8n webhook POST body encoding"
git push

# Create a feature branch:
git checkout -b feat/github-actions
git push -u origin feat/github-actions
# Open PR on GitHub
```

## What Goes in GitHub vs. Local

| Keep in GitHub | Keep Local Only |
|---|---|
| All source code | `data/` folder |
| README, docs | `uploads/` |
| n8n workflow JSON samples | `browser-profiles/` |
| GitHub Actions YAML | `.env` files |
| SKILL.md files | `*.db*` SQLite files |
