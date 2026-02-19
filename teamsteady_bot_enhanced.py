# -*- coding: utf-8 -*-
"""
Team Steady – Telegram Bot (EN) – Enhanced v7
- python-telegram-bot==13.15
- Team voice (we-form)
- SQLite lead tracking (persistent if Railway Volume mounted at /app/data)
- Deep-link tracking + auto strategy select:
    /start meta
    /start tiktok
    /start st50_meta
    /start st500_tiktok
- Strategy selection:
    1) Steady Trading 50 (accounts under $500) -> steadytradinggold + Vantage deep link
    2) Steady Trading 500 (accounts over $500) -> steadytradingteam + Vantage deep link
- Conversion improvements:
    (a) Ask account size immediately
    (b) After strategy selection: show Start Copying + Join Channel + Open Copy Trading
    (c) After opening copy link: "I enabled copying (Copied)" button to complete funnel
- Auto follow-ups (30m, 24h, 72h) without duplicates
- /stats (optional restricted by BOT_OWNER_ID)

IMPORTANT:
- Set TELEGRAM_BOT_TOKEN in Railway -> Variables
- Recommended: mount Railway Volume at /app/data
"""

import os
import logging
import sqlite3
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

# -------------------------
# Config (Railway Variables)
# -------------------------

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN env var (set it in Railway -> Variables).")

OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))  # optional: restrict /stats

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.getenv("DATA_DIR", "/app/data")
if not os.path.exists(DATA_DIR):
    DATA_DIR = BASE_DIR

DB_PATH = os.path.join(DATA_DIR, "leads.db")

LOGO_FILE = os.path.join(BASE_DIR, "logo_icon.png")
if not os.path.exists(LOGO_FILE):
    LOGO_FILE = os.path.join(BASE_DIR, "logo.png")

VANTAGE_HELP_FAQ = "https://global.vantagehelpcenter.com/hc/en-us/categories/5734807106447-Copy-Trading"

DISCLAIMER = "Trading involves risk. Past performance does not guarantee future results. This is not financial advice."

# -------------------------
# Strategies
# -------------------------

STRATEGY_50 = {
    "key": "st50",
    "name": "Steady Trading 50",
    "audience": "Accounts under $500",
    "channel_link": "https://t.me/steadytradinggold",
    "copy_link": "https://vantageapp.onelink.me/qaPD?af_xp=custom&pid=CopyTrading_Offer&af_web_dp=https%3A%2F%2Fsecure.vantagemarkets.com%2FcopyTrading%2Fdiscover%2FdiscoverDetail&deep_link_value=DQJC6YGBLQIAA===",
}

STRATEGY_500 = {
    "key": "st500",
    "name": "Steady Trading 500",
    "audience": "Accounts over $500",
    "channel_link": "https://t.me/steadytradingteam",
    "copy_link": "https://vantageapp.onelink.me/qaPD?af_xp=custom&pid=CopyTrading_Offer&af_web_dp=https%3A%2F%2Fsecure.vantagemarkets.com%2FcopyTrading%2Fdiscover%2FdiscoverDetail&deep_link_value=DPTCPDWZWAIAA===",
}

STRATEGIES = {
    STRATEGY_50["key"]: STRATEGY_50,
    STRATEGY_500["key"]: STRATEGY_500,
}

FAQ_ITEMS = [
    ("What is copy trading?", "You link your account and trades are mirrored automatically. You stay in control and can stop anytime."),
    ("What do we trade?", "We focus on XAUUSD (Gold)."),
    ("Do we guarantee profits?", "No. There are no guarantees in trading. Risk management comes first."),
    ("How do we manage risk?", "We follow strict risk rules, avoid over-trading, and focus on consistency."),
    ("How do we stop copying?", "You can pause/stop inside the Vantage copy trading interface at any time."),
    ("More detailed Vantage FAQ", f"Vantage Help Center (Copy Trading): {VANTAGE_HELP_FAQ}"),
]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("teamsteady")


# -------------------------
# SQLite storage
# -------------------------

def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def db_init() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = db_connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                chat_id TEXT PRIMARY KEY,
                first_seen TEXT,
                last_touch TEXT,
                stage TEXT,
                source TEXT,
                name TEXT,
                strategy TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def upsert_lead(
    chat_id: int,
    stage: Optional[str] = None,
    source: Optional[str] = None,
    name: Optional[str] = None,
    strategy: Optional[str] = None,
) -> None:
    now = datetime.utcnow().isoformat()
    cid = str(chat_id)

    conn = db_connect()
    try:
        row = conn.execute("SELECT * FROM leads WHERE chat_id = ?", (cid,)).fetchone()

        if row is None:
            conn.execute(
                "INSERT INTO leads (chat_id, first_seen, last_touch, stage, source, name, strategy) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cid, now, now, stage or "start", source, name, strategy),
            )
        else:
            new_stage = stage if stage else row["stage"]
            new_source = source if source else row["source"]
            new_name = name if name else row["name"]
            new_strategy = strategy if strategy else row["strategy"]
            conn.execute(
                """
                UPDATE leads
                SET last_touch = ?, stage = ?, source = ?, name = ?, strategy = ?
                WHERE chat_id = ?
                """,
                (now, new_stage, new_source, new_name, new_strategy, cid),
            )

        conn.commit()
    finally:
        conn.close()


def get_lead(chat_id: int) -> Dict[str, Any]:
    conn = db_connect()
    try:
        row = conn.execute("SELECT * FROM leads WHERE chat_id = ?", (str(chat_id),)).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def count_group(col: str) -> Dict[str, int]:
    if col not in ("stage", "source", "strategy"):
        return {}
    conn = db_connect()
    try:
        rows = conn.execute(
            f"SELECT {col} AS k, COUNT(*) AS c FROM leads WHERE {col} IS NOT NULL AND {col} != '' GROUP BY {col}"
        ).fetchall()
        return {r["k"]: int(r["c"]) for r in rows}
    finally:
        conn.close()


def count_total() -> int:
    conn = db_connect()
    try:
        r = conn.execute("SELECT COUNT(*) AS c FROM leads").fetchone()
        return int(r["c"]) if r else 0
    finally:
        conn.close()


# -------------------------
# Deep-link parsing
# -------------------------

def parse_start_arg(arg: str) -> Dict[str, str]:
    out = {}
    if not arg:
        return out

    a = arg.strip().lower()[:60]
    a = a.replace("-", "_")
    parts = [p for p in a.split("_") if p]
    if not parts:
        return out

    for p in parts:
        if p in ("st50", "st500"):
            out["strategy"] = p
    for p in parts:
        if p in ("meta", "tiktok", "organic"):
            out["source"] = p

    return out


# -------------------------
# UI helpers
# -------------------------

def main_menu():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Start Copying (step-by-step)", callback_data="onb1")],
            [InlineKeyboardButton("🟦 Steady Trading 50 (Under $500)", callback_data="strat_st50")],
            [InlineKeyboardButton("🟩 Steady Trading 500 (Over $500)", callback_data="strat_st500")],
            [InlineKeyboardButton("📉 Risk & Rules", callback_data="risk")],
            [InlineKeyboardButton("❓ FAQ", callback_data="faq")],
            [InlineKeyboardButton("🧾 Contact Support", callback_data="support")],
        ]
    )


def account_size_prompt():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Under $500", callback_data="size_under_500")],
            [InlineKeyboardButton("Over $500", callback_data="size_over_500")],
            [InlineKeyboardButton("Skip (choose manually)", callback_data="back")],
        ]
    )


def action_buttons_for_strategy(strategy_key: str):
    s = STRATEGIES.get(strategy_key)
    if not s:
        return InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]])
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Start Copying", callback_data="onb1")],
            [InlineKeyboardButton("🚀 Open Copy Trading", url=s["copy_link"])],
            [InlineKeyboardButton("📣 Join Strategy Channel", url=s["channel_link"])],
            [InlineKeyboardButton("Back", callback_data="back")],
        ]
    )


def final_step_buttons(strategy_key: str):
    s = STRATEGIES.get(strategy_key)
    if not s:
        return InlineKeyboardMarkup([[InlineKeyboardButton("Back to Menu", callback_data="back")]])
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🚀 Open Copy Trading", url=s["copy_link"])],
            [InlineKeyboardButton("📣 Join Strategy Channel", url=s["channel_link"])],
            [InlineKeyboardButton("✅ I enabled copying (Copied)", callback_data="copied")],
            [InlineKeyboardButton("Back to Menu", callback_data="back")],
        ]
    )


def build_welcome(first_name: str, preselected: Optional[str] = None):
    name = first_name or "there"
    base = (
        f"Hey {name} 👋\n"
        "Welcome to Team Steady.\n\n"
        "We trade XAUUSD (Gold) with a simple goal: protect capital first, grow second.\n"
        "Here you get a clear setup guide, our rules, and transparent updates.\n\n"
    )
    if preselected and preselected in STRATEGIES:
        s = STRATEGIES[preselected]
        base += f"✅ Pre-selected: {s['name']} ({s['audience']})\n\n"
        base += "Tap ✅ Start Copying below when you are ready.\n\n"
    else:
        base += "First question (so we can guide you correctly): what is your account size?\n\n"
    base += DISCLAIMER
    return base


def strategy_text(strategy_key: str) -> str:
    s = STRATEGIES.get(strategy_key)
    if not s:
        return "Please choose a strategy from the menu.\n\n" + DISCLAIMER
    return (
        f"✅ Strategy selected: {s['name']}\n"
        f"Best for: {s['audience']}\n\n"
        "Next steps:\n"
        "1) Tap ✅ Start Copying (step-by-step)\n"
        "2) Or open Copy Trading now and join the strategy channel\n\n"
        + DISCLAIMER
    )


def _edit_or_send(query, text, reply_markup=None):
    try:
        query.edit_message_text(text=text, reply_markup=reply_markup, disable_web_page_preview=True)
    except Exception:
        try:
            query.message.reply_text(text=text, reply_markup=reply_markup, disable_web_page_preview=True)
        except Exception:
            pass


def remove_followups(job_queue, chat_id: int):
    names = [f"fu30_{chat_id}", f"fu24_{chat_id}", f"fu72_{chat_id}"]
    for n in names:
        for job in job_queue.get_jobs_by_name(n):
            job.schedule_removal()


def get_user_strategy(chat_id: int) -> str:
    rec = get_lead(chat_id)
    strat = rec.get("strategy") if rec else None
    return strat if strat in STRATEGIES else ""


# -------------------------
# Follow-ups
# -------------------------

def followup_30m(context: CallbackContext):
    chat_id = int(context.job.context)
    rec = get_lead(chat_id)
    if rec.get("stage") == "start":
        context.bot.send_message(
            chat_id,
            text=(
                "Quick reminder 👇\n\n"
                "Choose your strategy (Under $500 or Over $500) and then tap ✅ Start Copying.\n"
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


# -------------------------
# Handlers
# -------------------------

def start(update: Update, context: CallbackContext):
    db_init()

    user = update.effective_user
    chat_id = update.effective_chat.id

    start_arg = (context.args[0] or "").strip() if getattr(context, "args", None) and len(context.args) > 0 else ""
    parsed = parse_start_arg(start_arg)
    source = parsed.get("source") or "organic"
    strategy = parsed.get("strategy")

    upsert_lead(chat_id, stage="start", source=source, name=getattr(user, "first_name", None), strategy=strategy)

    welcome = build_welcome(getattr(user, "first_name", ""), preselected=strategy)

    try:
        if os.path.exists(LOGO_FILE):
            with open(LOGO_FILE, "rb") as f:
                update.message.reply_photo(photo=f, caption=welcome)
        else:
            update.message.reply_text(welcome)
    except Exception:
        update.message.reply_text(welcome)

    if strategy in STRATEGIES:
        update.message.reply_text("You can continue here:", reply_markup=action_buttons_for_strategy(strategy))
    else:
        update.message.reply_text("Choose your account size:", reply_markup=account_size_prompt())
        update.message.reply_text("Or use the full menu:", reply_markup=main_menu())

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

    # Account size quick choice -> auto strategy
    if d == "size_under_500":
        upsert_lead(chat_id, stage="strategy_selected", strategy="st50")
        _edit_or_send(q, strategy_text("st50"), reply_markup=action_buttons_for_strategy("st50"))
        return

    if d == "size_over_500":
        upsert_lead(chat_id, stage="strategy_selected", strategy="st500")
        _edit_or_send(q, strategy_text("st500"), reply_markup=action_buttons_for_strategy("st500"))
        return

    # Manual strategy selection
    if d == "strat_st50":
        upsert_lead(chat_id, stage="strategy_selected", strategy="st50")
        _edit_or_send(q, strategy_text("st50"), reply_markup=action_buttons_for_strategy("st50"))
        return

    if d == "strat_st500":
        upsert_lead(chat_id, stage="strategy_selected", strategy="st500")
        _edit_or_send(q, strategy_text("st500"), reply_markup=action_buttons_for_strategy("st500"))
        return

    # New: Copied button (complete funnel)
    if d == "copied":
        strategy_key = get_user_strategy(chat_id)
        upsert_lead(chat_id, stage="copied")
        if strategy_key in STRATEGIES:
            s = STRATEGIES[strategy_key]
            _edit_or_send(
                q,
                "✅ Great — copying is enabled!\n\n"
                f"Next: make sure you joined the strategy channel for updates:\n{s['channel_link']}\n\n"
                "If you ever want to pause/stop, you can do it inside Vantage.\n\n"
                + DISCLAIMER,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back to Menu", callback_data="back")]]),
            )
        else:
            _edit_or_send(
                q,
                "✅ Great — copying is enabled!\n\n"
                "Next: join your strategy channel for updates.\n\n"
                + DISCLAIMER,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back to Menu", callback_data="back")]]),
            )
        return

    if d == "onb1":
        strategy_key = get_user_strategy(chat_id)
        if not strategy_key:
            _edit_or_send(
                q,
                "Before we start, choose your strategy:\n\n"
                "Under $500 -> Steady Trading 50\n"
                "Over $500  -> Steady Trading 500\n\n"
                "Use the account size buttons or pick from the menu.\n\n"
                + DISCLAIMER,
                reply_markup=account_size_prompt(),
            )
            return

        upsert_lead(chat_id, stage="start_copying")
        _edit_or_send(
            q,
            "✅ Step 1 — Open Vantage & get your account ready\n\n"
            "If you already have an account, move to verification (KYC).\n\n"
            'When your account is created, type: "Done".\n\n'
            + DISCLAIMER,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]),
        )
        return

    if d == "risk":
        _edit_or_send(
            q,
            "📉 Risk & Rules\n\n"
            "We focus on:\n"
            "• Risk control first\n"
            "• Consistency over hype\n"
            "• Transparent updates\n\n"
            "Choose strategy by account size:\n"
            "• Under $500 -> Steady Trading 50\n"
            "• Over $500  -> Steady Trading 500\n\n"
            + DISCLAIMER,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]),
        )
        return

    if d == "faq":
        lines = ["❓ FAQ\n"]
        for qtxt, atxt in FAQ_ITEMS:
            lines.append(f"• {qtxt}\n{atxt}\n")
        lines.append(DISCLAIMER)
        _edit_or_send(
            q,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]),
        )
        return

    if d == "support":
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Open Support", url="https://t.me/steadysupport")],
                [InlineKeyboardButton("Back", callback_data="back")],
            ]
        )
        _edit_or_send(
            q,
            "🧾 Support\n\n"
            "Write your question here, or open support using the button below.\n\n"
            + DISCLAIMER,
            reply_markup=kb,
        )
        return

    if d == "back":
        _edit_or_send(q, "Back to menu.", reply_markup=main_menu())
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
            + DISCLAIMER
        )
        return

    if t == "verified":
        upsert_lead(chat_id, stage="verified")
        update.message.reply_text(
            "✅ Step 3 — Add Funds\n\n"
            "Fund your account with an amount you are comfortable with.\n\n"
            "Choose strategy by account size:\n"
            "• Under $500 -> Steady Trading 50\n"
            "• Over $500  -> Steady Trading 500\n\n"
            'When complete, type: "Funded".\n\n'
            + DISCLAIMER
        )
        return

    if t == "funded":
        strategy_key = get_user_strategy(chat_id)
        if strategy_key not in STRATEGIES:
            update.message.reply_text(
                "Almost done! Choose your strategy first:\n\n"
                "Under $500 -> Steady Trading 50\n"
                "Over $500  -> Steady Trading 500\n\n"
                "Then type: Funded\n\n"
                + DISCLAIMER
            )
            return

        s = STRATEGIES[strategy_key]
        upsert_lead(chat_id, stage="funded")

        update.message.reply_text(
            "✅ Step 4 — Activate Copy Trading\n\n"
            f"Selected strategy: {s['name']}\n"
            f"Best for: {s['audience']}\n\n"
            "Tap Open Copy Trading, enable copying, then press ✅ I enabled copying.\n\n"
            + DISCLAIMER,
            reply_markup=final_step_buttons(strategy_key),
            disable_web_page_preview=True,
        )
        return

    if t in ("/start", "start"):
        start(update, context)
        return

    update.message.reply_text("Please use the menu buttons, or type /start.")


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


def main():
    db_init()
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("stats", stats))
    dp.add_handler(CallbackQueryHandler(on_button))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, on_text))

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
