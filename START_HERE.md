# Telegram Setup — DO THIS FIRST

Your Telegram bot token is the only thing needed to make Telegram work.

## Step 1 — Get your bot token (2 minutes)

1. Open Telegram
2. Search for **@BotFather** and start a chat
3. Send: `/newbot`
4. BotFather asks for a name — give it anything (e.g. "My Agent Bot")
5. BotFather asks for a username — must end in "bot" (e.g. "myAgenticOSBot")
6. BotFather gives you a bot token; keep it in your local environment.
7. **Copy that token**

## Step 2 — Paste it in AgenticOS

1. Open **http://127.0.0.1:8765**
2. Click **Telegram** in the sidebar (✈ icon)
3. Paste your token in the input box
4. Click **Connect bot**

That's it — Telegram is live. Start chatting with your bot on Telegram and your agents will respond.

---

# GitHub Setup — Run this when you're awake

```bash
cd ~/Desktop/Personal-OS
gh auth login
```

Then open **https://github.com/login/device** and enter the code shown.
After that, run:
```bash
gh repo create agentic-os --public --push
```
