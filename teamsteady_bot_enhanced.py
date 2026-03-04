import os
import logging

import psycopg2
from psycopg2.extras import RealDictCursor

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext, MessageHandler, Filters

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# =========================
# ENV
# =========================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0") or 0)

BRAND_NAME = os.getenv("BRAND_NAME", "MCM Trading")

# Links used in onboarding (override in Railway Variables if needed)
VANTAGE_OPEN_ACCOUNT_LINK = os.getenv("VANTAGE_OPEN_ACCOUNT_LINK", "https://www.vantagemarkets.com/open-live-account/")
COPY_TRADING_LINK = os.getenv("COPY_TRADING_LINK", "https://vantageapp.onelink.me/qaPD?af_xp=custom&pid=CopyTrading_Offer&af_web_dp=https%3A%2F%2Fsecure.vantagemarkets.com%2FcopyTrading%2Fdiscover%2FdiscoverDetail&deep_link_value=DQUK56OSJIIAA===")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "")   # optional (Telegram channel)
SUPPORT_LINK = os.getenv("SUPPORT_LINK", "")   # optional (support chat/channel)

# =========================
# DB helpers
# =========================
def db_conn():
    if not DATABASE_URL:
        return None
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def ensure_tables():
    conn = db_conn()
    if conn is None:
        logger.warning("DATABASE_URL not set. Running without DB.")
        return
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    tg_user_id BIGINT,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    start_param TEXT,
                    last_step TEXT
                );
                """
            )
    finally:
        conn.close()


def insert_lead(update: Update, start_param: str = "", last_step: str = ""):
    conn = db_conn()
    if conn is None:
        return
    u = update.effective_user
    if not u:
        return
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO leads (tg_user_id, username, first_name, last_name, start_param, last_step)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (u.id, u.username, u.first_name, u.last_name, start_param, last_step),
            )
    except Exception as e:
        logger.exception("DB write failed: %s", e)
    finally:
        conn.close()


# =========================
# Callbacks
# =========================
CB_STEP1 = "step1"
CB_STEP2 = "step2"
CB_STEP3 = "step3"
CB_STEP4 = "step4"
CB_RISK = "risk"
CB_FAQ = "faq"
CB_BACK = "back"

# =========================
# Keyboards
# =========================
def kb_main():
    rows = [
        [InlineKeyboardButton("Step 1 — Open Vantage account", callback_data=CB_STEP1)],
        [InlineKeyboardButton("Step 2 — Fund your account", callback_data=CB_STEP2)],
        [InlineKeyboardButton("Step 3 — Strategy access", callback_data=CB_STEP3)],
        [InlineKeyboardButton("Step 4 — Telegram updates", callback_data=CB_STEP4)],
        [
            InlineKeyboardButton("⚠️ Risk & Rules", callback_data=CB_RISK),
            InlineKeyboardButton("❓ FAQ", callback_data=CB_FAQ),
        ],
    ]
    if SUPPORT_LINK:
        rows.append([InlineKeyboardButton("Support", url=SUPPORT_LINK)])
    return InlineKeyboardMarkup(rows)


# =========================
# Commands
# =========================
def start(update: Update, context: CallbackContext):
    start_param = context.args[0] if context.args else ""
    insert_lead(update, start_param=start_param, last_step="start")

    msg = (
        f"👋 Welcome to *{BRAND_NAME}*\n\n"
        "Use the buttons below to onboard.\n\n"
        "*Important:* Trading involves risk. You can lose money."
    )
    update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb_main())


def help_cmd(update: Update, context: CallbackContext):
    update.message.reply_text("Use /start to open the onboarding menu.")


def stats(update: Update, context: CallbackContext):
    if BOT_OWNER_ID and update.effective_user and update.effective_user.id != BOT_OWNER_ID:
        update.message.reply_text("Not authorized.")
        return

    conn = db_conn()
    if conn is None:
        update.message.reply_text("DB not configured (DATABASE_URL missing).")
        return

    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) AS total FROM leads;")
            total = cur.fetchone()["total"]
            cur.execute(
                "SELECT start_param, COUNT(*) AS c FROM leads GROUP BY start_param ORDER BY c DESC NULLS LAST LIMIT 10;"
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    lines = [f"📊 Leads total: *{total}*\n", "*Top start params:*"]
    for r in rows:
        sp = r["start_param"] or "(none)"
        lines.append(f"• `{sp}` — {r['c']}")
    update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# Optional: reply if user types "start" without slash
def on_text(update: Update, context: CallbackContext):
    txt = (update.message.text or "").strip().lower()
    if txt == "start":
        start(update, context)


# =========================
# Callbacks
# =========================
def on_back(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    q.edit_message_text(
        f"Menu — *{BRAND_NAME}*\nChoose a step:",
        parse_mode="Markdown",
        reply_markup=kb_main(),
    )


def on_steps(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    data = q.data

    if data == CB_STEP1:
        insert_lead(update, last_step="step1")
        text = (
            "*Step 1 — Open your Vantage account*\n\n"
            "To access the copy trading strategy, you first need an active trading account with Vantage.\n\n"
            "If you do not already have one, open a live account using the button below.\n\n"
            "Once your account is created, return here and continue to Step 2."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Open Vantage Account", url=VANTAGE_OPEN_ACCOUNT_LINK)],
            [InlineKeyboardButton("Next ➜ Step 2", callback_data=CB_STEP2)],
            [InlineKeyboardButton("⬅️ Back", callback_data=CB_BACK)],
        ])
        q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
        return

    if data == CB_STEP2:
        insert_lead(update, last_step="step2")
        text = (
            "*Step 2 — Fund your account*\n\n"
            "To begin copying the strategy, your Vantage account needs to be funded.\n\n"
            "You are free to deposit any amount that suits your risk tolerance and financial situation.\n\n"
            "Many participants choose to start with *around $500*, but this is only an example and not a requirement.\n\n"
            "Once your account is funded, proceed to Step 3."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("I’ve funded my account ➜ Step 3", callback_data=CB_STEP3)],
            [InlineKeyboardButton("⬅️ Back", callback_data=CB_BACK)],
        ])
        q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
        return

    if data == CB_STEP3:
        insert_lead(update, last_step="step3")
        text = (
            "*Step 3 — Strategy access*\n\n"
            "You can preview the strategy on Vantage before deciding to copy.\n\n"
            "Trades will only copy after you activate the strategy.\n\n"
            "You remain in full control of your account."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("👀 Preview strategy", url=COPY_TRADING_LINK)],
            [InlineKeyboardButton("✅ Copy strategy", url=COPY_TRADING_LINK)],
            [InlineKeyboardButton("Next ➜ Step 4", callback_data=CB_STEP4)],
            [InlineKeyboardButton("⬅️ Back", callback_data=CB_BACK)],
        ])
        q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
        return

    if data == CB_STEP4:
        insert_lead(update, last_step="step4")
        text = (
            "*Step 4 — Telegram updates*\n\n"
            "Join our Telegram channel to receive strategy updates, trade notes, and important announcements.\n\n"
            "This is where we share performance updates, market commentary, and operational messages related to the strategy."
        )
        rows = []
        if CHANNEL_LINK:
            rows.append([InlineKeyboardButton("📣 Open Telegram channel", url=CHANNEL_LINK)])
        rows += [[InlineKeyboardButton("✅ Back to menu", callback_data=CB_BACK)]]
        q.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
        return

    if data == CB_RISK:
        insert_lead(update, last_step="risk")
        text = (
            "*Risk & Rules*\n\n"
            "• Trading is risky — you can lose some or all of your capital.\n"
            "• Past performance is not indicative of future results.\n"
            "• You remain responsible for your account and can stop copying anytime.\n"
            "• Only trade with money you can afford to lose.\n\n"
            "By continuing, you acknowledge these risks."
        )
        q.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=CB_BACK)]]),
        )
        return

    if data == CB_FAQ:
        insert_lead(update, last_step="faq")
        text = (
            "*FAQ*\n\n"
            "*Do I need trading experience?*\n"
            "No. Copying is automatic, but you should understand the risks.\n\n"
            "*Do you have access to my funds?*\n"
            "No. Your funds remain in your own Vantage account.\n\n"
            "*Can I stop copying?*\n"
            "Yes — you can stop at any time in your copy settings.\n\n"
            "*Why Telegram?*\n"
            "For updates, notes, and announcements."
        )
        q.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=CB_BACK)]]),
        )
        return


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

    ensure_tables()

    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_cmd))
    dp.add_handler(CommandHandler("stats", stats))

    # Optional: handle user typing "start" without slash
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, on_text))

    dp.add_handler(CallbackQueryHandler(on_back, pattern=f"^{CB_BACK}$"))
    dp.add_handler(CallbackQueryHandler(on_steps, pattern="^(step1|step2|step3|step4|risk|faq)$"))

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()

