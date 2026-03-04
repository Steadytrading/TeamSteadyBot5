# -*- coding: utf-8 -*-
"""
MCM Trading – Telegram Bot (EN) – Postgres v9 (stable)
- python-telegram-bot==13.15
- Postgres via DATABASE_URL (Railway)
- Team voice (we-form)
- Single master strategy (Gold / XAUUSD)
- st50 / st500 deep-links are kept for tracking only
- Funnel steps: Done -> Verified -> Funded -> Copied button
- FAQ includes Vantage Copy Trading FAQ link
- Follow-ups (30m, 24h, 72h) via JobQueue (no duplicates)
"""

import os
import logging
import psycopg2
from datetime import datetime
from typing import Optional, Dict, Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
    CallbackContext,
)

# =========================
# CONFIG / ENV
# =========================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcmtrading")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))

# Railway sometimes exposes different names; we accept fallbacks.
DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or os.getenv("DATABASE_PRIVATE_URL")
    or os.getenv("DATABASE_PUBLIC_URL")
)

if not TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")
if not DATABASE_URL:
    raise RuntimeError("Missing DATABASE_URL (or DATABASE_PRIVATE_URL / DATABASE_PUBLIC_URL)")

VANTAGE_HELP_FAQ = "https://global.vantagehelpcenter.com/hc/en-us/categories/5734807106447-Copy-Trading"
DISCLAIMER = "Trading involves risk. Past performance does not guarantee future results. This is not financial advice."

# =========================
# STRATEGY (single master account)
# =========================

BRAND_NAME = os.getenv("BRAND_NAME", "MCM Trading")

# You can keep using st50 / st500 deep-links for tracking from ads/landing page.
# Both map to the same master strategy (single provider account).
COPY_TRADING_LINK = os.getenv("COPY_TRADING_LINK", "https://example.com/SET_COPY_TRADING_LINK")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/SET_CHANNEL_LINK")
SUPPORT_LINK = os.getenv("SUPPORT_LINK", "https://t.me/SET_SUPPORT_LINK")

STRATEGY_MASTER = {
    "key": "master",
    "name": f"{BRAND_NAME} — Gold (XAUUSD)",
    "audience": "All account sizes (copied automatically)",
    "channel_link": CHANNEL_LINK,
    "copy_link": COPY_TRADING_LINK,
}

# Aliases used only for attribution/analytics (small vs large CTA), not for different strategies.
STRATEGIES = {
    "st50": STRATEGY_MASTER,
    "st500": STRATEGY_MASTER,
    "master": STRATEGY_MASTER,
}

FAQ_ITEMS = [
    ("What is copy trading?", "You link your account and trades are mirrored automatically. You stay in control and can stop anytime."),
    ("What do we trade?", "We focus on XAUUSD (Gold)."),
    ("Do we guarantee profits?", "No. There are no guarantees in trading. Risk management comes first."),
    ("How do we manage risk?", "We follow strict risk rules, avoid over-trading, and focus on consistency."),
    ("How do we stop copying?", "You can pause/stop inside the Vantage copy trading interface at any time."),
    ("More detailed Vantage FAQ", f"Vantage Help Center (Copy Trading): {VANTAGE_HELP_FAQ}"),
]

# =========================
# DB (Postgres)
# =========================

def db_conn():
    # Railway Postgres typically requires SSL in hosted environments.
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def db_init():
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS leads (
            chat_id TEXT PRIMARY KEY,
            first_seen TIMESTAMP NOT NULL,
            last_touch TIMESTAMP NOT NULL,
            stage TEXT,
            source TEXT,
            name TEXT,
            strategy TEXT
        );
        """
    )
    conn.commit()
    cur.close()
    conn.close()


def upsert_lead(
    chat_id: int,
    stage: Optional[str] = None,
    source: Optional[str] = None,
    name: Optional[str] = None,
    strategy: Optional[str] = None,
):
    now = datetime.utcnow()
    cid = str(chat_id)

    conn = db_conn()
    cur = conn.cursor()

    cur.execute("SELECT chat_id, stage, source, name, strategy FROM leads WHERE chat_id = %s", (cid,))
    row = cur.fetchone()

    if row is None:
        cur.execute(
            """
            INSERT INTO leads (chat_id, first_seen, last_touch, stage, source, name, strategy)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (cid, now, now, stage or "start", source, name, strategy),
        )
    else:
        # Keep existing values when None provided
        existing_stage, existing_source, existing_name, existing_strategy = row[1], row[2], row[3], row[4]
        new_stage = stage if stage is not None else existing_stage
        new_source = source if source is not None else existing_source
        new_name = name if name is not None else existing_name
        new_strategy = strategy if strategy is not None else existing_strategy

        cur.execute(
            """
            UPDATE leads
            SET last_touch = %s, stage = %s, source = %s, name = %s, strategy = %s
            WHERE chat_id = %s
            """,
            (now, new_stage, new_source, new_name, new_strategy, cid),
        )

    conn.commit()
    cur.close()
    conn.close()


def get_lead(chat_id: int) -> Dict[str, Any]:
    cid = str(chat_id)
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT chat_id, first_seen, last_touch, stage, source, name, strategy FROM leads WHERE chat_id = %s", (cid,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return {}

    return {
        "chat_id": row[0],
        "first_seen": row[1],
        "last_touch": row[2],
        "stage": row[3],
        "source": row[4],
        "name": row[5],
        "strategy": row[6],
    }


def count_total() -> int:
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM leads")
    total = int(cur.fetchone()[0])
    cur.close()
    conn.close()
    return total


def count_group(col: str) -> Dict[str, int]:
    if col not in ("stage", "source", "strategy"):
        return {}
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT {col}, COUNT(*) FROM leads WHERE {col} IS NOT NULL AND {col} != '' GROUP BY {col}")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {str(r[0]): int(r[1]) for r in rows}


# =========================
# DEEP LINK PARSING
# =========================

def parse_start_arg(arg: str) -> Dict[str, str]:
    out = {}
    if not arg:
        return out

    a = arg.strip().lower()[:80].replace("-", "_")
    parts = [p for p in a.split("_") if p]

    for p in parts:
        if p in ("st50", "st500"):
            out["strategy"] = p
    for p in parts:
        if p in ("meta", "tiktok", "organic"):
            out["source"] = p

    return out


def get_user_strategy(chat_id: int) -> str:
    rec = get_lead(chat_id)
    strat = rec.get("strategy")
    return strat if strat in STRATEGIES else ""


# =========================
# UI HELPERS
# =========================

def main_menu() -> InlineKeyboardMarkup:
    # Main actions (single master strategy)
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Start Copying (step-by-step)", callback_data="onb1")],
            [InlineKeyboardButton("🚀 Open Copy Trading", url=COPY_TRADING_LINK)],
            [InlineKeyboardButton("📣 Join Telegram Channel", url=CHANNEL_LINK)],
            [InlineKeyboardButton("📉 Risk & Rules", callback_data="risk")],
            [InlineKeyboardButton("❓ FAQ", callback_data="faq")],
            [InlineKeyboardButton("🧾 Contact Support", callback_data="support")],
        ]
    )


def account_size_prompt() -> InlineKeyboardMarkup:
    # Optional segmentation for guidance + analytics (same strategy either way)
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Under $500", callback_data="size_under_500")],
            [InlineKeyboardButton("Over $500", callback_data="size_over_500")],
            [InlineKeyboardButton("Skip", callback_data="back")],
        ]
    )


def action_buttons_for_strategy(strategy_key: str) -> InlineKeyboardMarkup:
    # strategy_key may be st50 / st500 (segmentation) or master
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Start Copying", callback_data="onb1")],
            [InlineKeyboardButton("🚀 Open Copy Trading", url=COPY_TRADING_LINK)],
            [InlineKeyboardButton("📣 Join Telegram Channel", url=CHANNEL_LINK)],
            [InlineKeyboardButton("Back", callback_data="back")],
        ]
    )


def final_step_buttons(strategy_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🚀 Open Copy Trading", url=COPY_TRADING_LINK)],
            [InlineKeyboardButton("📣 Join Telegram Channel", url=CHANNEL_LINK)],
            [InlineKeyboardButton("✅ I enabled copying (Copied)", callback_data="copied")],
            [InlineKeyboardButton("Back to Menu", callback_data="back")],
        ]
    )


def build_welcome(first_name: str, preselected: Optional[str] = None) -> str:
    name = first_name or "there"
    return (
        f"Hey {name} 👋\n"
        f"Welcome to {BRAND_NAME}.\n\n"
        "We run a structured Gold (XAUUSD) copy trading strategy.\n"
        "Our focus: protect capital first, grow second — no hype.\n\n"
        "If you want, you can tell us your account size so we can guide you better (optional).\n\n"
        + DISCLAIMER
    )


def strategy_text(strategy_key: str) -> str:
    # strategy_key here is used only for segmentation (small vs large CTA)
    label = "Under $500" if strategy_key == "st50" else ("Over $500" if strategy_key == "st500" else "Not specified")
    return (
        f"✅ Noted — account size: {label}.\n\n"
        "Next steps:\n"
        "1) Tap ✅ Start Copying (step-by-step)\n"
        "2) Or open Copy Trading now and enable copying\n\n"
        + DISCLAIMER
    )


def edit_or_send(query, text: str, reply_markup=None):
    try:
        query.edit_message_text(text=text, reply_markup=reply_markup, disable_web_page_preview=True)
    except Exception:
        try:
            query.message.reply_text(text=text, reply_markup=reply_markup, disable_web_page_preview=True)
        except Exception:
            pass


# =========================
# FOLLOW-UPS
# =========================

def remove_followups(job_queue, chat_id: int):
    names = [f"fu30_{chat_id}", f"fu24_{chat_id}", f"fu72_{chat_id}"]
    for n in names:
        for job in job_queue.get_jobs_by_name(n):
            job.schedule_removal()


def followup_30m(context: CallbackContext):
    chat_id = int(context.job.context)
    rec = get_lead(chat_id)
    if rec.get("stage") == "start":
        context.bot.send_message(
            chat_id,
            text=(
                "Quick reminder 👇\n\n"
                "Tap ✅ Start Copying to follow the setup guide. (Account size selection is optional.)\n"
                'When your Vantage account is created, type: "Done".\n\n'
                + DISCLAIMER
            ),
        )


def followup_24h(context: CallbackContext):
    chat_id = int(context.job.context)
    rec = get_lead(chat_id)
    if rec.get("stage") in ("start", "done"):
        context.bot.send_message(
            chat_id,
            text=(
                "How’s it going?\n\n"
                "Once verification (KYC) is completed, you’re one step away from copy trading.\n"
                'Type: "Verified" when ready.\n\n'
                + DISCLAIMER
            ),
        )


def followup_72h(context: CallbackContext):
    chat_id = int(context.job.context)
    rec = get_lead(chat_id)
    if rec.get("stage") in ("start", "done", "verified"):
        context.bot.send_message(
            chat_id,
            text=(
                "Need a hand?\n\n"
                'Add funds at your own pace. When you’re done, type: "Funded".\n'
                "If you have questions, tap Contact Support in the menu.\n\n"
                + DISCLAIMER
            ),
        )

# =========================
# HANDLERS
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    source = "unknown"

    if context.args:
        source = context.args[0]

    print(f"User came from: {source}")

    text = f"""
Welcome to *{BRAND_NAME}*

Source: {source}

Start copying our gold strategy below.
"""

    await update.message.reply_text(
        text,
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

    welcome = build_welcome(getattr(user, "first_name", ""), preselected=seg)
    update.message.reply_text(welcome, disable_web_page_preview=True)

    update.message.reply_text("Optional: select your account size (for guidance):", reply_markup=account_size_prompt())
    update.message.reply_text("Main menu:", reply_markup=main_menu())

    remove_followups(context.job_queue, chat_id)
    context.job_queue.run_once(followup_30m, 30 * 60, context=chat_id, name=f"fu30_{chat_id}")
    context.job_queue.run_once(followup_24h, 24 * 60 * 60, context=chat_id, name=f"fu24_{chat_id}")
    context.job_queue.run_once(followup_72h, 72 * 60 * 60, context=chat_id, name=f"fu72_{chat_id}")

def on_button(update: Update, context: CallbackContext):
    db_init()

    q = update.callback_query
    q.answer()
    d = q.data
    chat_id = q.message.chat.id

    # account size -> strategy
    if d == "size_under_500":
        upsert_lead(chat_id, stage="strategy_selected", strategy="st50")
        edit_or_send(q, strategy_text("st50"), reply_markup=action_buttons_for_strategy("st50"))
        return

    if d == "size_over_500":
        upsert_lead(chat_id, stage="strategy_selected", strategy="st500")
        edit_or_send(q, strategy_text("st500"), reply_markup=action_buttons_for_strategy("st500"))
        return

    # manual strategy selection
    if d == "strat_st50":
        upsert_lead(chat_id, stage="strategy_selected", strategy="st50")
        edit_or_send(q, strategy_text("st50"), reply_markup=action_buttons_for_strategy("st50"))
        return

    if d == "strat_st500":
        upsert_lead(chat_id, stage="strategy_selected", strategy="st500")
        edit_or_send(q, strategy_text("st500"), reply_markup=action_buttons_for_strategy("st500"))
        return

    # onboarding
    if d == "onb1":
        # Optional segmentation may be stored as st50 / st500, but strategy is always the same master account.
        strategy_key = get_user_strategy(chat_id) or "master"
        if strategy_key not in STRATEGIES:
            strategy_key = "master"

        upsert_lead(chat_id, stage="start_copying", strategy=strategy_key if strategy_key != "master" else None)
        edit_or_send(
            q,
            "✅ Step 1 — Open Vantage & get your account ready\n\n"
            "If you already have an account, move to verification (KYC).\n\n"
            'When your account is created, type: "Done".\n\n'
            + DISCLAIMER,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]),
        )
        return

    # copied button
    if d == "copied":
        strategy_key = get_user_strategy(chat_id)
        upsert_lead(chat_id, stage="copied")

        if strategy_key in STRATEGIES:
            s = STRATEGIES[strategy_key]
            edit_or_send(
                q,
                "✅ Great — copying is enabled!\n\n"
                f"Next: make sure you joined the strategy channel for updates:\n{s['channel_link']}\n\n"
                "If you ever want to pause/stop, you can do it inside Vantage.\n\n"
                + DISCLAIMER,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back to Menu", callback_data="back")]]),
            )
        else:
            edit_or_send(
                q,
                "✅ Great — copying is enabled!\n\n"
                "Next: join your strategy channel for updates.\n\n"
                + DISCLAIMER,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back to Menu", callback_data="back")]]),
            )
        return

    # info screens
    if d == "risk":
        edit_or_send(
            q,
            "📉 Risk & Rules\n\n"
            "We focus on:\n"
            "• Risk control first\n"
            "• Consistency over hype\n"
            "• Transparent updates\n\n"
            "Optional guidance by account size:\n"
            "• Under $500: start small and avoid over-leverage\n"
            "• Over $500: keep risk controlled and copy proportionally\n\n"
            + DISCLAIMER,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]),
        )
        return
        return

    if d == "faq":
        lines = ["❓ FAQ\n"]
        for qtxt, atxt in FAQ_ITEMS:
            lines.append(f"• {qtxt}\n{atxt}\n")
        lines.append(DISCLAIMER)
        edit_or_send(
            q,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]),
        )
        return

    if d == "support":
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Open Support", url=SUPPORT_LINK)],
                [InlineKeyboardButton("Back", callback_data="back")],
            ]
        )
        edit_or_send(
            q,
            "🧾 Support\n\n"
            "Write your question here, or open support using the button below.\n\n"
            + DISCLAIMER,
            reply_markup=kb,
        )
        return

    if d == "back":
        edit_or_send(q, "Back to menu.", reply_markup=main_menu())
        return


def on_text(update: Update, context: CallbackContext):
    db_init()

    chat_id = update.effective_chat.id
    t = (update.message.text or "").strip().lower()

    if t == "done":
        upsert_lead(chat_id, stage="done")
        update.message.reply_text(
            "✅ Step 2 — Verification (KYC)\n\n"
            "Complete KYC (ID + proof of address).\n\n"
            'When ready, type: "Verified".\n\n'
            + DISCLAIMER,
            reply_markup=main_menu(),
        )
        return

    if t == "verified":
        upsert_lead(chat_id, stage="verified")
        update.message.reply_text(
            "✅ Step 3 — Add Funds\n\n"
            "Fund your account with an amount you are comfortable with.\n\n"
            "Optional: if you want, select your account size in the menu (for guidance only).\n\n"
            'When complete, type: "Funded".\n\n'
            + DISCLAIMER,
            reply_markup=main_menu(),
        )
        return

    if t == "funded":
        strategy_key = get_user_strategy(chat_id) or "master"
        if strategy_key not in STRATEGIES:
            strategy_key = "master"

        # keep segmentation (st50/st500) if available, otherwise store nothing
        upsert_lead(chat_id, stage="funded", strategy=strategy_key if strategy_key in ("st50", "st500") else None)
        seg = "Under $500" if strategy_key == "st50" else ("Over $500" if strategy_key == "st500" else "Not specified")

        update.message.reply_text(
            "✅ Step 4 — Activate Copy Trading\n\n"
            f"Account size (optional): {seg}\n"
            f"Strategy: {STRATEGY_MASTER['name']}\n\n"
            "Tap Open Copy Trading, enable copying, then press ✅ I enabled copying.\n\n"
            + DISCLAIMER,
            reply_markup=final_step_buttons(strategy_key),
            disable_web_page_preview=True,
        )
        return

    if t in ("/start", "start"):
        start(update, context)
        return

    update.message.reply_text("Please use the menu buttons, or type /start.", reply_markup=main_menu())
def stats(update: Update, context: CallbackContext):
    db_init()

    if OWNER_ID and update.effective_user.id != OWNER_ID:
        update.message.reply_text("Stats are restricted.")
        return

    total = count_total()
    stages = count_group("stage")
    sources = count_group("source")
    strategies = count_group("strategy")

    msg = [f"Leads: {total}", ""]
    msg.append("Stages:")
    for k in sorted(stages.keys()):
        msg.append(f"- {k}: {stages[k]}")

    if sources:
        msg.append("")
        msg.append("Sources:")
        for k in sorted(sources.keys()):
            msg.append(f"- {k}: {sources[k]}")

    if strategies:
        msg.append("")
        msg.append("Strategies:")
        label_map = {"st50": STRATEGY_50["name"], "st500": STRATEGY_500["name"]}
        for k in sorted(strategies.keys()):
            msg.append(f"- {label_map.get(k, k)}: {strategies[k]}")

    update.message.reply_text("\n".join(msg))


# =========================
# MAIN
# =========================

def main():
    db_init()

    logger.info("=== MCM TRADING BOT STARTED (Postgres v9) ===")
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("stats", stats))
    dp.add_handler(CallbackQueryHandler(on_button))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, on_text))

    logger.info("=== STARTING TELEGRAM POLLING NOW ===")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
