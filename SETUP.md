# AgenticOS Setup Guide

## Quick Start

```bash
cd ~/Desktop/Personal-OS
python3 server.py
# Open http://127.0.0.1:8765
```

## 1. Telegram Bot Setup

### Step 1 — Create your bot
1. Open Telegram and chat with **@BotFather**
2. Send: `/newbot`
3. Follow prompts: give it a name and username
4. Copy the bot token it gives you (format: `123456789:ABCdef...`)

### Step 2 — Add your token to AgenticOS
Edit the `.env` file in the Personal-OS folder:

```bash
nano ~/.bash_profile
# Add this line:
export TELEGRAM_BOT_TOKEN="YOUR_TOKEN_HERE"
```

Then in your terminal:
```bash
export TELEGRAM_BOT_TOKEN="YOUR_TOKEN_HERE"
cd ~/Desktop/Personal-OS
python3 server.py
```

### Step 3 — Link your Telegram account
1. Open AgenticOS in your browser
2. Go to **Telegram** page (✈ icon in sidebar)
3. Click **Check for pending messages** or send `/start` to your bot on Telegram
4. Your chat ID will be auto-detected
5. Click **Link Chat** to connect your account

### Step 4 — Chat with your agents from Telegram
Send a message to your bot:
- `@ceo find me jobs in Saudi Arabia`
- `@job status`
- `@dad check email`

---

## 2. Ollama (Local AI Models)

Ollama is already running at `localhost:11434` with these models:
- `qwen2.5:7b` — fast general purpose
- `hermes3:8b` — reasoning
- `qwen3:30b` — large reasoning
- `llama3.1:8b` — general
- `codellama:7b` — code
- `mistral:7b` — fast
- `nomic-embed-text` — embeddings

To add more models:
```bash
ollama pull llama3.3:70b
ollama pull deepseek-coder:33b
```

---

## 3. Claude Code Setup (optional — for best results)

```bash
# Install if needed
npm install -g @anthropic-ai/claude-code

# Authenticate
claude auth

# Verify
claude auth status
```

---

## 4. Codex CLI Setup (optional)

```bash
# Install if needed
npm install -g opencode-ai

# Authenticate
codex auth

# Verify
codex --version
```

---

## 5. Obsidian Vault (Memory)

Your vault is at:
```
~/Documents/Hermes Obsidian/Hermes/
```

Agent memory notes already exist:
- `CEO Agent.md` — company goals, delegation strategy
- `Job Application Agent.md` — target roles, resume summary
- `Dad Email Agent.md` — family priorities, check-in schedule
- `Hermes Memory.md` — personal context

To edit agent memory, open the corresponding file in Obsidian.

---

## 6. n8n Automation (optional)

1. Set up n8n at `https://your-n8n.com`
2. Create workflows with webhook triggers
3. Add webhook URL to `.env`: `N8N_WEBHOOK_URL=https://...`
4. Configure per-agent webhooks in the **n8n** page of AgenticOS

---

## 7. Notion Integration (optional)

1. Go to https://www.notion.so/my-integrations
2. Create a new integration
3. Copy the API key
4. Add to `.env`: `NOTION_API_KEY=secret_...`

---

## Environment Variables

Create a `.env` file in the Personal-OS folder:

```bash
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
NOTION_API_KEY=secret_abc123...
N8N_WEBHOOK_URL=https://your-n8n.com/webhook/

# Job Hunter (see docs/JOB-HUNTER.md) — easiest: python3 -m jobhunter setup
JOBHUNTER_EMAIL=you@gmail.com
JOBHUNTER_EMAIL_PASSWORD=abcdefghijklmnop   # Gmail App Password, not your normal password
RAPIDAPI_KEY=...                            # optional: JSearch / Google for Jobs (Indeed, Bayt, Glassdoor…)
SERPAPI_KEY=...                             # optional: Google for Jobs via SerpAPI
```

---

## Troubleshooting

**Server won't start?**
```bash
lsof -ti:8765 | xargs kill -9 2>/dev/null
python3 server.py
```

**Tests failing?**
```bash
python3 -m unittest discover tests/ -v
```

**Ollama not responding?**
```bash
ollama serve
# In another terminal:
curl http://localhost:11434/api/tags
```

**Browser shows old UI?**
Hard refresh: `Cmd+Shift+R` (Mac) or `Ctrl+Shift+R` (Windows)

**Telegram not connecting?**
1. Verify bot token is correct
2. Make sure you started a chat with your bot on Telegram first
3. Check the Telegram page in AgenticOS for error messages

---

## Features

- 🤖 **Page Agent** — Click the 🤖 button bottom-right on any page to edit it with AI
- 📋 **Quick Create Agent** — Click `＋` on the home page to create a new agent
- 📊 **Command Center** — Home page shows tasks, schedules, delegations, team status
- 🔍 **Search** — Search bar on home page finds anything
- 🎤 **Voice** — Use 🎤 for speech-to-text, 🔊 for text-to-speech in any chat
- 🌙 **Dark Mode** — Page Agent understands "dark mode" commands
- 🔗 **Delegations** — CEO routes tasks to specialist agents automatically
- 💾 **Vault Memory** — Agents remember context across sessions via Obsidian

---

## Keyboard Shortcuts

- `Cmd/Ctrl + K` — Open command palette
- `Cmd/Ctrl + Shift + R` — Hard refresh (clear cache)
- `Esc` — Close modals

---

## GitHub Push

Once you have `gh` authenticated:

```bash
cd ~/Desktop/Personal-OS

# Option A — OAuth (will open browser)
gh auth login
# Use code from terminal at github.com/login/device

# Option B — Paste token directly
gh auth login --with-token

# Then push
gh repo create agentic-os --public --push
# Or push to existing repo:
git remote add origin https://github.com/YOUR_USERNAME/agentic-os.git
git push -u origin main
```
