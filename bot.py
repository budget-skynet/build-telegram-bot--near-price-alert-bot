import os
import logging
import aiohttp
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
NEAR_RPC = "https://rpc.mainnet.near.org"
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"

# In-memory alert store: { user_id: [ {id, direction, target, triggered}, ... ] }
_alerts: dict[int, list[dict]] = {}
_alert_counter: dict[int, int] = {}

# ---------------------------------------------------------------------------
# 1. NEAR RPC helper
# ---------------------------------------------------------------------------
async def _rpc(method: str, params: dict | list) -> dict:
    """Send a JSON-RPC request to the NEAR mainnet RPC endpoint."""
    payload = {
        "jsonrpc": "2.0",
        "id": "near-price-bot",
        "method": method,
        "params": params,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(NEAR_RPC, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            return await resp.json()

# ---------------------------------------------------------------------------
# 2. NEAR helper functions
# ---------------------------------------------------------------------------
async def get_near_price_usd() -> float:
    """Fetch current NEAR price in USD from CoinGecko."""
    params = {"ids": "near", "vs_currencies": "usd"}
    async with aiohttp.ClientSession() as session:
        async with session.get(COINGECKO_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return float(data["near"]["usd"])


async def get_near_block_info() -> dict:
    """Fetch the latest NEAR block information via RPC."""
    result = await _rpc("block", {"finality": "final"})
    block = result.get("result", {})
    header = block.get("header", {})
    return {
        "height": header.get("height", "N/A"),
        "timestamp_ns": header.get("timestamp", 0),
        "hash": header.get("hash", "N/A"),
    }


def add_alert(user_id: int, direction: str, target: float) -> int:
    """Add a price alert for a user. direction: 'above' or 'below'."""
    _alerts.setdefault(user_id, [])
    _alert_counter.setdefault(user_id, 0)
    _alert_counter[user_id] += 1
    alert_id = _alert_counter[user_id]
    _alerts[user_id].append({
        "id": alert_id,
        "direction": direction,
        "target": target,
        "triggered": False,
    })
    return alert_id


def get_alerts(user_id: int) -> list[dict]:
    """Return all active (non-triggered) alerts for a user."""
    return [a for a in _alerts.get(user_id, []) if not a["triggered"]]


def remove_alert(user_id: int, alert_id: int) -> bool:
    """Remove an alert by ID. Returns True if found and removed."""
    alerts = _alerts.get(user_id, [])
    for i, alert in enumerate(alerts):
        if alert["id"] == alert_id:
            alerts.pop(i)
            return True
    return False


async def check_alerts_for_user(user_id: int, current_price: float) -> list[dict]:
    """Check which alerts have been triggered for a user at the given price."""
    triggered = []
    for alert in _alerts.get(user_id, []):
        if alert["triggered"]:
            continue
        if alert["direction"] == "above" and current_price >= alert["target"]:
            alert["triggered"] = True
            triggered.append(alert)
        elif alert["direction"] == "below" and current_price <= alert["target"]:
            alert["triggered"] = True
            triggered.append(alert)
    return triggered

# ---------------------------------------------------------------------------
# 3. /start and /help handlers
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message explaining the bot."""
    user = update.effective_user
    text = (
        f"👋 Hello, {user.first_name}! Welcome to the *NEAR Price Alert Bot*.\n\n"
        "I watch the NEAR token price and notify you when your target is hit.\n\n"
        "📌 *Quick Commands:*\n"
        "• /price — current NEAR price\n"
        "• /setalert above 6.50 — alert when price goes above $6.50\n"
        "• /setalert below 4.00 — alert when price drops below $4.00\n"
        "• /alerts — list your active alerts\n"
        "• /removealert <id> — delete an alert\n"
        "• /checkalerts — manually check your alerts now\n"
        "• /blockinfo — latest NEAR block info\n"
        "• /help — show this message\n\n"
        "Set your first alert and I'll ping you the moment it triggers! 🚀"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display detailed help."""
    text = (
        "🤖 *NEAR Price Alert Bot — Help*\n\n"
        "*Commands:*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📈 `/price`\n"
        "  → Fetch the current NEAR/USD price.\n\n"
        "🔔 `/setalert <above|below> <price>`\n"
        "  → Set a price alert.\n"
        "  Example: `/setalert above 6.50`\n\n"
        "📋 `/alerts`\n"
        "  → List all your active alerts.\n\n"
        "🗑 `/removealert <id>`\n"
        "  → Cancel an alert by its ID.\n"
        "  Example: `/removealert 3`\n\n"
        "🔍 `/checkalerts`\n"
        "  → Manually check if any of your alerts have triggered.\n\n"
        "⛓ `/blockinfo`\n"
        "  → Show the latest NEAR blockchain block information.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Alerts are checked every time you use `/checkalerts`. "
        "For automatic checking, the bot polls every 60 seconds if you have active alerts."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ---------------------------------------------------------------------------
# 4. Command handlers
# ---------------------------------------------------------------------------
async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetch and display the current NEAR price."""
    try:
        price = await get_near_price_usd()
        text = (
            f"💰 *NEAR Price*\n\n"
            f"Current Price: `${price:,.4f} USD`\n\n"
            f"_Source: CoinGecko_"
        )
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as exc:
        logger.error("price_command error: %s", exc)
        await update.message.reply_text("❌ Failed to fetch NEAR price. Please try again shortly.")


async def setalert_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Set a price alert.
    Usage: /setalert <above|below> <price>
    Example: /setalert above 6.50
    """
    args = context.args
    if len(args) != 2:
        await update.message.reply_text(
            "⚠️ Usage: `/setalert <above|below> <price>`\n"
            "Example: `/setalert above 6.50`",
            parse_mode="Markdown",
        )
        return

    direction = args[0].lower()
    if direction not in ("above", "below"):
        await update.message.reply_text(
            "⚠️ Direction must be `above` or `below`.\n"
            "Example: `/setalert below 4.00`",
            parse_mode="Markdown",
        )
        return

    try:
        target = float(args[1])
        if target <= 0:
            raise ValueError("Price must be positive.")
    except ValueError:
        await update.message.reply_text("⚠️ Please provide a valid positive number for the price.")
        return

    user_id = update.effective_user.id
    alert_id = add_alert(user_id, direction, target)

    emoji = "📈" if direction == "above" else "📉"
    await update.message.reply_text(
        f"{emoji} *Alert Set!*\n\n"
        f"Alert ID: `{alert_id}`\n"
        f"Trigger: NEAR goes *{direction}* `${target:,.4f}`\n\n"
        f"Use /checkalerts to check manually, or I'll notify you automatically.",
        parse_mode="Markdown",
    )


async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all active alerts for the user."""
    user_id = update.effective_user.id
    active = get_alerts(user_id)

    if not active:
        await update.message.reply_text(
            "📋 You have no active alerts.\n\nUse `/setalert above 6.50` to create one.",
            parse_mode="Markdown",
        )
        return

    lines = ["📋 *Your Active Alerts:*\n"]
    for alert in active:
        emoji = "📈" if alert["direction"] == "above" else "📉"
        lines.append(
            f"{emoji} ID `{alert['id']}` — NEAR *{alert['direction']}* `${alert['target']:,.4f}`"
        )
    lines.append("\nUse `/removealert <id>` to cancel an alert.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def removealert_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Remove an alert by ID.
    Usage: /removealert <id>
    """
    args = context.args
    if len(args) != 1:
        await update.message.reply_text(
            "⚠️ Usage: `/removealert <id>`\nExample: `/removealert 2`",
            parse_mode="Markdown",
        )
        return

    try:
        alert_id = int(args[0])
    except ValueError:
        await update.message.reply_text("⚠️ Alert ID must be an integer.")
        return

    user_id = update.effective_user.id
    removed = remove_alert(user_id, alert_id)

    if removed:
        await update.message.reply_text(
            f"🗑 Alert `{alert_id}` has been removed.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"❌ No active alert with ID `{alert_id}` found.",
            parse_mode="Markdown",
        )


async def checkalerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manually check all active alerts against the current NEAR price."""
    user_id = update.effective_user.id
    active = get_alerts(user_id)

    if not active:
        await update.message.reply_text(
            "📋 You have no active alerts to check.\n\nCreate one with `/setalert above 6.50`.",
            parse_mode="Markdown",
        )
        return

    try:
        price = await get_near_price_usd()
    except Exception as exc:
        logger.error("checkalerts price fetch error: %s", exc)
        await update.message.reply_text("❌ Could not fetch NEAR price right now. Try again later.")
        return

    triggered = await check_alerts_for_user(user_id, price)

    if triggered:
        lines = [f"🚨 *Alert(s) Triggered!* — NEAR is `${price:,.4f}`\n"]
        for alert in triggered:
            emoji = "📈" if alert["direction"] == "above" else "📉"
            lines.append(
                f"{emoji} Alert `{alert['id']}`: NEAR went *{alert['direction']}* `${alert['target']:,.4f}` ✅"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    else:
        remaining = get_alerts(user_id)
        lines = [
            f"✅ *No alerts triggered yet.*\n",
            f"Current NEAR price: `${price:,.4f}`\n",
            f"Active alerts: {len(remaining)}\n",
        ]
        for alert in remaining:
            emoji = "📈" if alert["direction"] == "above" else "📉"
            lines.append(
                f"{emoji} ID `{alert['id']}` — {alert['direction']} `${alert['target']:,.4f}`"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def blockinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetch and display the latest NEAR block information."""
    try:
        info = await get_near_block_info()
        # Convert nanoseconds timestamp to seconds
        ts_ns = info["timestamp_ns"]
        ts_s = ts_ns // 1_000_000_000 if ts_ns else 0

        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(ts_s, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if ts_s else "N/A"

        text = (
            "⛓ *Latest NEAR Block*\n\n"
            f"Height:    `{info['height']:,}`\n"
            f"Hash:      `{info['hash'][:20]}…`\n"
            f"Timestamp: `{dt}`"
        )
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as exc:
        logger.error("blockinfo_command error: %s", exc)
        await update.message.reply_text("❌ Failed to fetch block info from NEAR RPC.")

def main() -> None:
    logging.basicConfig(level=logging.INFO)
    token = os.environ.get("BOT_TOKEN", "")
    application = ApplicationBuilder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("price", price_command))
    application.add_handler(CommandHandler("setalert", setalert_command))
    application.add_handler(CommandHandler("alerts", alerts_command))
    application.add_handler(CommandHandler("removealert", removealert_command))
    application.add_handler(CommandHandler("checkalerts", checkalerts_command))
    application.run_polling()

if __name__ == "__main__":
    main()
