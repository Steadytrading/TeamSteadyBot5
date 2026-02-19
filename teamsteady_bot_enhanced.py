# -*- coding: utf-8 -*-

import os
import logging
import psycopg2
from urllib.parse import urlparse
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
    CallbackContext,
)

# ==========================
# ENV
# ==========================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))

if not TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

if not DATABASE_URL:
    raise RuntimeError("Missing DATABASE_URL")

logging.basicConfig(level=logging.INFO)

# ==========================
# DB
# ==========================

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            chat_id TEXT PRIMARY KEY,
            first_seen TIMESTAMP,
            last_touch TIMESTAMP,
            stage TEXT,
            source TEXT,
            name TEXT,
            strategy TEXT
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

def upsert_lead(chat_id, stage=None, source=None, name=None, strategy=None):
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.utcnow()

    cur.execute("SELECT chat_id FROM leads WHERE chat_id = %s", (str(chat_id),))
    exists = cur.fetchone()

    if not exists:
        cur.execute("""
            INSERT INTO leads (chat_id, first_seen, last_touch, stage, source, name, strategy)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (str(chat_id), now, now, stage, source, name, strategy))
    else:
        cur.execute("""
            UPDATE leads
            SET last_touch = %s,
                stage = COALESCE(%s, stage),
                source = COALESCE(%s, source),
                name = COALESCE(%s, name),
                strategy = COALESCE(%s, strategy)
            WHERE chat_id = %s
        """, (now, stage, source, name, strategy, str(chat_id)))

    conn.commit()
    cur.close()
    conn.close()

def get_lead(chat_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT strategy FROM leads WHERE chat_id = %s", (str(chat_id),))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None

# ==========================
# STRATEGIES
# ==========================

STRATEGIES = {
    "st50": {
        "name": "Steady Trading 50",
        "audience": "Accounts under $500",
        "channel": "https://t.me/steadytradinggold",
        "copy": "https://vantageapp.onelink.me/qaPD?deep_link_value=DQJC6YGBLQIAA===",
    },
    "st500": {
        "name": "Steady Trading 500",
        "audience": "Accounts over $500",
        "channel": "https://t.me/steadytradingteam",
        "copy": "https://vantageapp.onelink.me/qaPD?deep_link_value=DPTCPDWZWAIAA===",
    }
}

DISCLAIMER = "Trading involves risk. Past performance does not guarantee future results."

# ==========================
# BOT FLOW
# ==========================

def start(update: Update, context: CallbackContext):
    init_db()
    user = update.effective_user
    chat_id = update.effective_chat.id

    source = "organic"
    strategy = None

    if context.args:
        arg = context.args[0].lower()
        if "meta" in arg: source = "meta"
        if "tiktok" in arg: source = "tiktok"
        if "st50" in arg: strategy = "st50"
        if "st500" in arg: strategy = "st500"

    upsert_lead(chat_id, stage="start", source=source, name=user.first_name, strategy=strategy)

    update.message.reply_text(
        f"Hey {user.first_name} 👋\n\n"
        "Welcome to Team Steady.\n\n"
        "We trade XAUUSD with strict risk control.\n\n"
        "What is your account size?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Under $500", callback_data="st50")],
            [InlineKeyboardButton("Over $500", callback_data="st500")]
        ])
    )

def choose_strategy(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    chat_id = query.message.chat.id
    strategy = query.data

    upsert_lead(chat_id, stage="strategy_selected", strategy=strategy)

    s = STRATEGIES[strategy]

    query.edit_message_text(
        f"✅ {s['name']}\n"
        f"Best for: {s['audience']}\n\n"
        "Open Copy Trading below and enable copying.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Open Copy Trading", url=s["copy"])],
            [InlineKeyboardButton("Join Strategy Channel", url=s["channel"])],
            [InlineKeyboardButton("I enabled copying", callback_data="copied")]
        ])
    )

def copied(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    chat_id = query.message.chat.id

    upsert_lead(chat_id, stage="copied")

    query.edit_message_text(
        "🔥 Perfect. Copying is now active.\n\n"
        "Stay updated in the strategy channel.\n\n"
        + DISCLAIMER
    )

def stats(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    update.message.reply_text("Stats connected to Postgres successfully.")

def main():
    init_db()
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("stats", stats))
    dp.add_handler(CallbackQueryHandler(choose_strategy, pattern="^st50$|^st500$"))
    dp.add_handler(CallbackQueryHandler(copied, pattern="^copied$"))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
