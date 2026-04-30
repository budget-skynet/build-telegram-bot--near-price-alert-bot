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

# ---------------------------------------------------------------------------
# In-memory alert storage  {user_id: [{"direction": "above"/"below",
#                                       "target": float,
#                                       "id": int}, ...]}
# ---------------------------------------------------------------------------
alerts: dict[int, list[dict]] = {}
_alert_counter: dict[int, int] = {}

# ---------------------------------------------------------------------------
# 1. NEAR RPC helper
# ---------------------------------------------------------------------------
async def _rpc(method: str, params: dict | list) -> dict:
    """Send a JSON-RPC request to the NEAR mainnet RPC endpoint."""
    payload = {
        "jsonrpc": "2.0",
        "id": "near_price_bot",
        "method": method,
        "params": params,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            NEAR_RPC,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

# ---------------------------------------------------------------------------
# 2. NEAR helper functions
# ---------------------------------------------------------------------------
async def get_near_price_usd() -> float:
    """Fetch the current NEAR/USD price from CoinGecko."""
    params = {"ids": "near", "vs_currencies": "usd"}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            COINGECKO_URL,
            params=params,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return float(data["near"]["usd"])


async def get_near_block_info() -> dict:
    """Return the latest finalized block info via NEAR RPC."""
    result = await _rpc("block", {"finality": "final"})
    header = result.get("result", {}).get("header", {})
    return {
        "height": header.get("height"),
        "timestamp_ns": header.get("timestamp"),
        "hash": header.get("hash"),
    }


def add_alert(user_id: int, direction: str, target: float) -> int:
    """
    Register a new price alert for *user_id*.

    direction : "above" | "below"
    target    : USD price threshold
    Returns the new alert id.
    """
    _alert_counter[user_id] = _alert_counter.get(user_id, 0) + 1
    alert_id = _alert_counter[user_id]
    alerts.setdefault(user_id, []).append(
        {"id": alert_id, "direction": direction, "target": target}
    )
    return alert_id


def remove_alert(user_id: int, alert_id: int) -> bool:
    """Delete alert *alert_id* for *user_id*. Returns True if found."""
    user_alerts = alerts.get(user_id, [])
    new_list = [a for a in user_alerts if a["id"] != alert_id]
    if len(new_list) == len(user_alerts):
        return False
    alerts[user_id] = new_list
    return True


async def check_and_fire_alerts(current_price: float, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Compare *current_price* against every registered alert.
    Fire (and remove) any alert whose condition is satisfied.
    """
    fired: list[tuple[int, dict]] = []

    for user_id, user_alerts in list(alerts.items()):
        for alert in list(user_alerts):
            triggered = (
                alert["direction"] == "above" and current_price >= alert["target"]
            ) or (
                alert["direction"] == "below" and current_price <= alert["target"]
            )
            if triggered:
                fired.append((user_id, alert))

    for user_id, alert in fired:
        direction_word = "risen above" if alert["direction"] == "above" else "fallen below"
        msg = (
            f"🚨 *NEAR Price Alert Triggered!*\n\n"
            f"NEAR has {direction_word} your target of *${alert['target']:.4f}*.\n"
            f"Current price: *${current_price:.4f}*\n\n"
            f"Alert #{alert['id']} has been removed."
        )
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=msg,
                parse_mode="Markdown",
            )
        except Exception as exc:
            logger.warning("Failed to notify user %s: %s", user_id, exc)
        remove_alert(user_id, alert["id"])


# ---------------------------------------------------------------------------
# 3. /start and /help
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome message."""
    text = (
        "👋 *Welcome to the NEAR Price Alert Bot!*\n\n"
        "I watch the NEAR/USD price and notify you the moment it crosses "
        "your chosen threshold.\n\n"
        "Use /help to see all available commands."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all commands."""
    text = (
        "📖 *Available Commands*\n\n"
        "/price — Show the current NEAR/USD price\n"
        "/setalert `<above|below>` `<price>` — Set a price alert\n"
        "  _Example:_ `/setalert above 8.50`\n"
        "/listalerts — Show your active alerts\n"
        "/removealert `<id>` — Remove an alert by its ID\n"
        "/checkblock — Show the latest NEAR block info\n"
        "/help — Show this message"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# 4. Command handlers
# ---------------------------------------------------------------------------
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/price — Fetch and display the current NEAR price."""
    try:
        usd = await get_near_price_usd()
        await update.message.reply_text(
            f"💰 *NEAR / USD*\n\nCurrent price: *${usd:.4f}*",
            parse_mode="Markdown",
        )
    except Exception as exc:
        logger.error("price fetch error: %s", exc)
        await update.message.reply_text("⚠️ Could not fetch the price. Please try again later.")


async def setalert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/setalert <above|below> <price> — Register a new price alert."""
    args = context.args
    if len(args) != 2 or args[0].lower() not in ("above", "below"):
        await update.message.reply_text(
            "Usage: `/setalert <above|below> <price>`\nExample: `/setalert above 8.50`",
            parse_mode="Markdown",
        )
        return

    direction = args[0].lower()
    try:
        target = float(args[1])
    except ValueError:
        await update.message.reply_text("⚠️ Price must be a number, e.g. `8.50`.", parse_mode="Markdown")
        return

    user_id = update.effective_user.id
    alert_id = add_alert(user_id, direction, target)

    # Immediately check whether the alert is already satisfied
    try:
        current = await get_near_price_usd()
        await check_and_fire_alerts(current, context)
    except Exception:
        pass  # Non-fatal; alert is stored regardless

    await update.message.reply_text(
        f"✅ Alert #{alert_id} set!\n\n"
        f"I'll notify you when NEAR goes *{direction}* *${target:.4f}*.",
        parse_mode="Markdown",
    )


async def listalerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/listalerts — Show the caller's active alerts."""
    user_id = update.effective_user.id
    user_alerts = alerts.get(user_id, [])

    if not user_alerts:
        await update.message.reply_text("ℹ️ You have no active alerts. Use /setalert to create one.")
        return

    lines = ["📋 *Your Active Alerts*\n"]
    for alert in user_alerts:
        arrow = "⬆️" if alert["direction"] == "above" else "⬇️"
        lines.append(f"{arrow} Alert #{alert['id']} — NEAR {alert['direction']} *${alert['target']:.4f}*")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def removealert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/removealert <id> — Delete an alert by ID."""
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Usage: `/removealert <id>`\nFind IDs with /listalerts.",
            parse_mode="Markdown",
        )
        return

    user_id = update.effective_user.id
    alert_id = int(context.args[0])

    if remove_alert(user_id, alert_id):
        await update.message.reply_text(f"🗑️ Alert #{alert_id} has been removed.")
    else:
        await update.message.reply_text(
            f"⚠️ No alert with ID #{alert_id} found. Use /listalerts to see your alerts."
        )


async def checkblock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/checkblock — Display the latest NEAR block information."""
    try:
        info = await get_near_block_info()
        # Convert nanosecond timestamp to seconds
        ts_sec = (info.get("timestamp_ns") or 0) // 1_000_000_000
        from datetime import datetime, timezone
        dt_str = datetime.fromtimestamp(ts_sec, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        text = (
            "🔗 *Latest NEAR Block*\n\n"
            f"• Height : `{info.get('height')}`\n"
            f"• Time   : `{dt_str}`\n"
            f"• Hash   : `{info.get('hash')}`"
        )
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as exc:
        logger.error("checkblock error: %s", exc)
        await update.message.reply_text("⚠️ Could not fetch block info. Please try again later.")

def main() -> None:
    logging.basicConfig(level=logging.INFO)
    token = os.environ.get("BOT_TOKEN", "")
    application = ApplicationBuilder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CommandHandler("setalert", setalert))
    application.add_handler(CommandHandler("listalerts", listalerts))
    application.add_handler(CommandHandler("removealert", removealert))
    application.add_handler(CommandHandler("checkblock", checkblock))
    application.run_polling()

if __name__ == "__main__":
    main()
