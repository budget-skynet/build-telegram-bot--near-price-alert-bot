# NEAR Price Alert Bot

A Telegram bot that monitors the NEAR Protocol token price and notifies you when your target price is reached. Set custom alerts for price movements above or below specific thresholds and manage multiple alerts at once — all from within Telegram.

---

## Prerequisites

- Python 3.9 or higher
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- Internet access for live price data

---

## Installation

git clone https://github.com/your-username/near-price-alert-bot.git
cd near-price-alert-bot
pip install -r requirements.txt

---

## Configuration

1. Open Telegram and start a chat with [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts to create your bot
3. Copy the token provided and set it as an environment variable:

export BOT_TOKEN=your_telegram_bot_token_here

On Windows:

set BOT_TOKEN=your_telegram_bot_token_here

Optionally, create a `.env` file in the project root:

BOT_TOKEN=your_telegram_bot_token_here

---

## Running

python bot.py

The bot will start polling for updates. Keep this process running to receive alerts.

---

## Available Commands

| Command | Description |
|---|---|
| `/start` | Start the bot and see a welcome message |
| `/help` | Display all available commands and usage |
| `/price` | Get the current NEAR token price |
| `/setalert` | Set a new price alert (above or below a target) |
| `/alerts` | List all your active alerts |
| `/removealert` | Remove a specific alert by ID |
| `/checkalerts` | Manually trigger a check against all your active alerts |

---

## Deployment

For always-on hosting, deploy to **Railway** or **Heroku** by adding a `Procfile` with the line `worker: python bot.py` and pushing to your connected repository.

---

## Notes

- Price data is fetched from a public cryptocurrency API (CoinGecko or similar)
- Alerts are checked on a regular interval automatically in the background
- All alert data is stored per user session; a database integration is recommended for persistence in production