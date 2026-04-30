# NEAR Price Alert Bot

A Telegram bot that monitors the NEAR Protocol token price and sends you instant notifications when your target price is reached. Set custom alerts for price movements above or below a threshold and manage multiple alerts at once — all from within Telegram.

---

## Prerequisites

- Python 3.9+
- A Telegram account
- Bot token from [@BotFather](https://t.me/BotFather)

---

## Installation

git clone https://github.com/your-username/near-price-alert-bot.git
cd near-price-alert-bot
pip install -r requirements.txt

---

## Configuration

1. Open Telegram and start a chat with [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts to create your bot
3. Copy the token BotFather provides
4. Set it as an environment variable:

# Linux / macOS
export BOT_TOKEN="your_token_here"

# Windows
set BOT_TOKEN="your_token_here"

Optionally, create a `.env` file in the project root:

BOT_TOKEN=your_token_here

---

## Running

python bot.py

The bot will start polling for updates. Keep the terminal open or run it as a background process.

---

## Available Commands

| Command | Description |
|---|---|
| `/start` | Start the bot and see a welcome message |
| `/help` | Display usage instructions and tips |
| `/price` | Fetch the current NEAR token price |
| `/setalert` | Set a new price alert (above or below a target) |
| `/listalerts` | View all your active price alerts |
| `/removealert` | Delete a specific alert by ID |
| `/checkblock` | Check the latest NEAR blockchain block info |

---

## Deployment

**Railway (recommended):**

Add a `Procfile` to your project:

worker: python bot.py

Then push to Railway or Heroku and set `BOT_TOKEN` in the platform's environment variables dashboard. The bot runs as a background worker with no web server required.

---

## License

MIT