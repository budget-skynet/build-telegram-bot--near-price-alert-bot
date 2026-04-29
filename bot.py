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
# In-memory alert store  {user_id: [{"direction": "above"|"below", "price": float, "id": int}]}
# ---------------------------------------------------------------------------
_alerts: dict[int, list[dict]] = {}
_alert_counter: dict[int, int] = {}

# ---------------------------------------------------------------------------
# 1. NEAR RPC helper
# ---------------------------------------------------------------------------
async def _rpc(method: str, params: dict | list) -> dict:
    """Send a JSON-RPC request to the NEAR mainnet RPC endpoint."""
    payload = {
        "jsonrpc": "2.0",
        "id": "nearbot",
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
    """Fetch the current NEAR/USD price from CoinGecko."""
    params = {"ids": "near", "vs_currencies": "usd"}
    async with aiohttp.ClientSession() as session:
        async with session.get(COINGECKO_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return float(data["near"]["usd"])


async def get_near_block_height() -> int:
    """Return the latest finalized block height from the NEAR RPC."""
    result = await _rpc("block", {"finality": "final"})
    return result["result"]["header"]["height"]


async def get_near_validators_count() -> int:
    """Return the number of current validators on NEAR mainnet."""
    result = await _rpc("validators", [None])
    return len(result["result"]["current_validators"])


async def add_alert(user_id: int, direction: str, target_price: float) -> int:
    """
    Store a price alert for *user_id*.

    direction : "above" | "below"
    Returns the new alert's integer ID.
    """
    if user_id not in _alerts:
        _alerts[user_id] = []
        _alert_counter[user_id] = 0

    _alert_counter[user_id] += 1
    alert_id = _alert_counter[user_id]
    _alerts[user_id].append({"id": alert_id, "direction": direction, "price": target_price})
    return alert_id


async def check_and_fire_alerts(user_id: int, current_price: float) -> list[dict]:
    """
    Compare *current_price* against all stored alerts for *user_id*.

    Returns a list of alerts that were triggered and removes them from storage.
    """
    triggered = []
    remaining = []
    for alert in _alerts.get(user_id, []):
        hit = (alert["direction"] == "above" and current_price >= alert["price"]) or \
              (alert["direction"] == "below" and current_price <= alert["price"])
        if hit:
            triggered.append(alert)
        else:
            remaining.append(alert)
    _alerts[user_id] = remaining
    return triggered

# ---------------------------------------------------------------------------
# 3. /start and /help
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message with a quick-start guide."""
    text = (
        "👋 *Welcome to the NEAR Price Alert Bot!*\n\n"
        "I monitor the NEAR/USD price and notify you the moment your target is hit.\n\n"
        "📋 *Quick-start*\n"
        "• `/price` — current NEAR price\n"
        "• `/setalert above 7.50` — alert when price goes *above* $7.50\n"
        "• `/setalert below 4.00` — alert when price drops *below* $4.00\n"
        "• `/listalerts` — view your active alerts\n"
        "• `/deletealert <id>` — remove an alert\n"
        "• `/check` — manually check your alerts right now\n"
        "• `/stats` — NEAR network stats\n\n"
        "Type /help for the full command list."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the full command reference."""
    text = (
        "🤖 *NEAR Price Alert Bot — Command Reference*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💰 *Price*\n"
        "`/price` — Fetch the live NEAR/USD price.\n\n"
        "🔔 *Alerts*\n"
        "`/setalert above <price>` — Notify me when NEAR rises above `<price>` USD.\n"
        "`/setalert below <price>` — Notify me when NEAR falls below `<price>` USD.\n"
        "`/listalerts` — Show all your active alerts.\n"
        "`/deletealert <id>` — Delete the alert with the given ID.\n"
        "`/check` — Immediately check whether any alert has triggered.\n\n"
        "📊 *Network*\n"
        "`/stats` — Latest NEAR block height and validator count.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "_Alerts are checked every time you run_ `/check`_._"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ---------------------------------------------------------------------------
# 4. Command handlers
# ---------------------------------------------------------------------------
async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/price — show the current NEAR/USD price."""
    try:
        price = await get_near_price_usd()
        await update.message.reply_text(
            f"💲 *NEAR / USD*\n`${price:,.4f}`",
            parse_mode="Markdown",
        )
    except Exception as exc:
        logger.error("price_command error: %s", exc)
        await update.message.reply_text("⚠️ Could not fetch price right now. Please try again shortly.")


async def setalert_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/setalert above|below <price> — register a price alert."""
    args = context.args
    if len(args) != 2 or args[0].lower() not in ("above", "below"):
        await update.message.reply_text(
            "Usage: `/setalert above 7.50` or `/setalert below 4.00`",
            parse_mode="Markdown",
        )
        return

    direction = args[0].lower()
    try:
        target = float(args[1])
        if target <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Price must be a positive number, e.g. `5.25`.", parse_mode="Markdown")
        return

    user_id = update.effective_user.id
    alert_id = await add_alert(user_id, direction, target)

    emoji = "📈" if direction == "above" else "📉"
    await update.message.reply_text(
        f"{emoji} Alert #{alert_id} set!\n"
        f"I'll notify you when NEAR goes *{direction}* `${target:,.4f}` USD.",
        parse_mode="Markdown",
    )


async def listalerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/listalerts — list all active alerts for the calling user."""
    user_id = update.effective_user.id
    alerts = _alerts.get(user_id, [])

    if not alerts:
        await update.message.reply_text("You have no active alerts. Use /setalert to create one.")
        return

    lines = ["🔔 *Your active alerts:*\n"]
    for a in alerts:
        arrow = "⬆️" if a["direction"] == "above" else "⬇️"
        lines.append(f"{arrow} ID `{a['id']}` — NEAR *{a['direction']}* `${a['price']:,.4f}`")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def deletealert_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/deletealert <id> — remove a specific alert."""
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: `/deletealert <id>`", parse_mode="Markdown")
        return

    alert_id = int(context.args[0])
    user_id = update.effective_user.id
    original = _alerts.get(user_id, [])
    updated = [a for a in original if a["id"] != alert_id]

    if len(updated) == len(original):
        await update.message.reply_text(f"⚠️ No alert with ID `{alert_id}` found.", parse_mode="Markdown")
        return

    _alerts[user_id] = updated
    await update.message.reply_text(f"🗑️ Alert #{alert_id} deleted.", parse_mode="Markdown")


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/check — fetch current price and fire any matching alerts."""
    user_id = update.effective_user.id

    if not _alerts.get(user_id):
        await update.message.reply_text("You have no active alerts. Use /setalert to create one.")
        return

    try:
        price = await get_near_price_usd()
    except Exception as exc:
        logger.error("check_command price fetch error: %s", exc)
        await update.message.reply_text("⚠️ Could not fetch price. Please try again shortly.")
        return

    triggered = await check_and_fire_alerts(user_id, price)

    if triggered:
        lines = [f"🚨 *Alert triggered at* `${price:,.4f}` USD!\n"]
        for a in triggered:
            arrow = "⬆️" if a["direction"] == "above" else "⬇️"
            lines.append(f"{arrow} ID `{a['id']}` — NEAR went *{a['direction']}* `${a['price']:,.4f}`")
        lines.append("\n_These alerts have been removed._")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    else:
        remaining = len(_alerts.get(user_id, []))
        await update.message.reply_text(
            f"✅ No alerts triggered.\n"
            f"Current NEAR price: `${price:,.4f}` USD\n"
            f"Active alerts: {remaining}",
            parse_mode="Markdown",
        )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats — show NEAR network stats (block height + validator count)."""
    try:
        block_height = await get_near_block_height()
        validators = await get_near_validators_count()
        price = await get_near_price_usd()
        await update.message.reply_text(
            "📊 *NEAR Network Stats*\n\n"
            f"💲 Price:       `${price:,.4f}` USD\n"
            f"🧱 Block:       `{block_height:,}`\n"
            f"🏛️ Validators: `{validators}`",
            parse_mode="Markdown",
        )
    except Exception as exc:
        logger.error("stats_command error: %s", exc)
        await update.message.reply_text("⚠️ Could not retrieve network stats right now.")

def main() -> None:
    logging.basicConfig(level=logging.INFO)
    token = os.environ.get("BOT_TOKEN", "")
    application = ApplicationBuilder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("price", price_command))
    application.add_handler(CommandHandler("setalert", setalert_command))
    application.add_handler(CommandHandler("listalerts", listalerts_command))
    application.add_handler(CommandHandler("deletealert", deletealert_command))
    application.add_handler(CommandHandler("check", check_command))
    application.run_polling()

if __name__ == "__main__":
    main()
