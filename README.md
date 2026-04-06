# 🤖 Miracle Transfer Bot — Setup Guide

## What it does
- Agent types `/transfer` in Telegram → bot guides them step by step
- Bot posts formatted request to your group with **✅ Approve / ❌ Reject** buttons
- Only approved roles (MD, Supervisor, Area Manager, Accounts) can tap buttons
- Decision is stamped on the message + submitter gets a DM notification

---

## Step 1 — Create your bot (2 mins)

1. Open Telegram → search **@BotFather** → `/start`
2. Send `/newbot`
3. Name: `Miracle Transfer Bot`
4. Username: `MiracleGRP2ABot` (must end in `bot`)
5. Copy the token: `7123456789:AAFxxx...`

---

## Step 2 — Get your Group Chat ID

1. Add the bot to your Telegram group (make it an **Admin**)
2. Send any message in the group
3. Open this URL in your browser (replace TOKEN):
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
4. Look for `"chat": {"id": -100xxxxxxx}` — that negative number is your GROUP_ID

---

## Step 3 — Configure approvers

Edit your `.env` file — add the Telegram usernames (no @) of everyone who can approve:
```
APPROVERS=GT138888,brian_jw,kelvin555
```

---

## Step 4 — Deploy to Railway (free)

1. Create account at **railway.app**
2. New Project → **Deploy from GitHub repo**
3. Push this folder to a GitHub repo first:
   ```bash
   git init
   git add .
   git commit -m "initial"
   git remote add origin https://github.com/YOUR_USERNAME/miracle-bot.git
   git push -u origin main
   ```
4. In Railway → Add environment variables:
   - `BOT_TOKEN` = your token from BotFather
   - `GROUP_ID` = your group chat ID (negative number)
   - `APPROVERS` = comma-separated usernames

5. Deploy — Railway auto-detects Python and starts the bot.

---

## Step 5 — Test it

1. Open your Telegram group
2. Send `/transfer` to the bot in **private chat**
3. Follow the steps — bot posts to group when done
4. Tap ✅ Approve or ❌ Reject in the group

---

## Commands

| Command | Who | What |
|---|---|---|
| `/transfer` | Any agent | Start a new transfer request |
| `/history` | Anyone | View last 10 decisions |
| `/cancel` | Anyone | Cancel current request |
| `/start` | Anyone | Show help |

---

## Running locally (optional, for testing)

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your values
python bot.py
```

---

## File structure
```
miracle-bot/
├── bot.py              # Main bot code
├── requirements.txt    # Python dependencies
├── railway.toml        # Railway deployment config
├── .env.example        # Environment variable template
├── .gitignore          # Excludes .env and history from git
└── history.json        # Auto-created, stores decisions
```
