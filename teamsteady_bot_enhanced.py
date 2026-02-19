# -*- coding: utf-8 -*-
"""
Team Steady – Telegram Bot (EN) – Enhanced v3 (human + more info)
- Lead tagging on /start (writes to leads.json)
- Source tracking via deep links: t.me/TeamSteadybot?start=meta / ?start=tiktok
- Track selection: Low Risk vs Medium Risk
- Funnel stage tracking (done/verified/funded/copied)
- Auto follow-ups via JobQueue (30m, 24h, 72h)
- /stats for owner to see simple metrics

Requires: python-telegram-bot==13.15
"""

import os
import json
import logging
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
    CallbackContext,
)

# --- Config (set these in Railway -> Variables) ---

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN env var (set it in Railway → Variables).")

VANTAGE_LINK = "https://www.vantagemarkets.com/open-live-account/?affid=MjMxNDQ0MzY=&gad_source=1&gad_campaignid=23494365984&gbraid=0AAAABCsAuaye6WQIqKss-cJVC3PS6OGm2&gclid=Cj0KCQiAy6vMBhDCARIsAK8rOgkm1I-nxMmY7LlohkY2Eg_lvTgCkY81ol1DgxQne7lSWlNLJ2Wdj8YaAvZCEALw_wcB"
COPY_LINK = "https://vantageapp.onelink.me/qaPD?af_xp=custom&pid=CopyTrading_Offer&af_web_dp=https%3A%2F%2Fsecure.vantagemarkets.com%2FcopyTrading%2Fdiscover%2FdiscoverDetail&deep_link_value=DPTCPDWZWAIAA=="
CHANNEL_LINK = "https://t.me/steadytradingteam"
SUPPORT_LINK = "https://t.me/steadysupport"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Prefer logo_icon.png if you have it; otherwise keep logo.png
LOGO_FILE = os.path.join(BASE_DIR, "logo_icon.png")
if not os.path.exists(LOGO_FILE):
    LOGO_FILE = os.path.join(BASE_DIR, "logo.png")

LEADS_FILE = os.path.join(BASE_DIR, "leads.json")

DISCLAIMER = "Trading involves risk. Past performance does not guarantee future results. This is not financial advice."
OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))  # optional: set your Telegram user id to restrict /stats

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("teamsteady")


# --- “Human” content blocks ---

TRACKS = {
    "low": {
        "title": "🟢 Low Risk (starting Monday)",
        "start_date": "2026-02-16",
        "starting_balance": 883,
        "style": "More conservative approach focused on capital preservation and smoother equity curve.",
    },
    "medium": {
        "title": "🟠 Medium Risk (track record since Jan 12)",
        "start_date": "2026-01-12",
        "starting_balance": 500,
        "style": "Higher tempo than Low Risk, still rule-based. This is the documented journey account.",
    },
}

FAQ_ITEMS = [
    ("What is copy trading?", "You link your account and trades are mirrored automatically. You stay in control and can stop anytime."),
    ("What do you trade?", "I focus on XAUUSD (Gold)."),
    ("Do you guarantee profits?", "No. There are no guarantees in trading. Risk comes first."),
    ("How do you manage risk?", "I use strict risk rules, avoid over-trading, and focus on consistency."),
    ("How do I stop copying?", "You can pause/stop in the copy trading interface at any time."),
]


# --- Persistence helpers ---

def load_leads():
    if not os.path.exists(LEADS_FILE):
        return {}
    try:
        with open(LEADS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_leads(data):
    with open(LEADS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)



# lead structure:
# { str(chat_id): {"first_seen":iso, "stage":"start|done|verified|funded|copied|...", "last_touch":iso, "source":"meta|tiktok|...", "name":"..." , "track":"low|medium"} }

def tag_lead(chat_id, stage="start", source=None, name=None, track=None):
    leads = load_leads()
    now = datetime.utcnow().isoformat()
    key = str(chat_id)

    rec = leads.get(key, {"first_seen": now})
    rec["last_touch"] = now
    rec["stage"] = stage or rec.get("stage", "start")

    if source:
        rec["source"] = source
    if name:
        rec["name"] = name
    if track:
        rec["track"] = track

    leads[key] = rec
    save_leads(leads)


# --- UI ---

def main_menu():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Start Copying (step-by-step)", callback_data="onb1")],
            [InlineKeyboardButton("🟢 Low Risk Track", callback_data="track_low")],
            [InlineKeyboardButton("🟠 Medium Risk Track", callback_data="track_medium")],
            [InlineKeyboardButton("📊 Results (overview)", callback_data="results")],
            [InlineKeyboardButton("📉 Risk & Drawdown", callback_data="risk")],
            [InlineKeyboardButton("❓ FAQ", callback_data="faq")],
            [InlineKeyboardButton("🧾 Contact Support", callback_data="agent")],
        ]
    )


def build_welcome(first_name: str):
    name = first_name or "there"
    return (
        f"Hey {name} 👋\n"
        "Welcome to Team Steady.\n\n"
        "I trade XAUUSD (Gold) with strict risk rules and full transparency.\n"
        "Pick a track (Low Risk or Medium Risk), and I’ll guide you through the setup.\n\n"
        f"{DISCLAIMER}"
    )


# --- Handlers ---

def start(update: Update, context: CallbackContext):
    user = update.effective_user
    chat_id = update.effective_chat.id

    # Deep link source tracking:
    # t.me/TeamSteadybot?start=meta   /   t.me/TeamSteadybot?start=tiktok
    source = None
    if getattr(context, "args", None) and len(context.args) > 0:
        source = (context.args[0] or "").strip().lower()[:40] or None

    tag_lead(chat_id, "start", source=source, name=getattr(user, "first_name", None))
    welcome = build_welcome(getattr(user, "first_name", ""))

    try:
        if os.path.exists(LOGO_FILE):
            with open(LOGO_FILE, "rb") as f:
                update.message.reply_photo(f, caption=welcome)
        else:
            update.message.reply_text(welcome)
    except Exception:
        update.message.reply_text(welcome)

    update.message.reply_text("Choose an option below:", reply_markup=main_menu())

    # schedule follow-ups
    context.job_queue.run_once(followup_30m, 30 * 60, context=chat_id, name=f"fu30_{chat_id}")
    context.job_queue.run_once(followup_24h, 24 * 60 * 60, context=chat_id, name=f"fu24_{chat_id}")
    context.job_queue.run_once(followup_72h, 72 * 60 * 60, context=chat_id, name=f"fu72_{chat_id}")


def followup_30m(context: CallbackContext):
    chat_id = context.job.context
    leads = load_leads()
    rec = leads.get(str(chat_id), {})
    if rec.get("stage") == "start":
        context.bot.send_message(
            chat_id,
            text=(
                "Quick reminder 👇\n\n"
                "Step 1 is creating your Vantage account:\n"
                f"👉 {VANTAGE_LINK}\n\n"
                'When you’re done, type: "Done"'
            ),
        )


def followup_24h(context: CallbackContext):
    chat_id = context.job.context
    leads = load_leads()
    rec = leads.get(str(chat_id), {})
    if rec.get("stage") in ("start", "done"):
        context.bot.send_message(
            chat_id,
            text=(
                "How’s it going?\n\n"
                "Once verification (KYC) is completed, you’re one step away from copy trading.\n"
                'Type: "Verified" when ready.'
            ),
        )


def followup_72h(context: CallbackContext):
    chat_id = context.job.context
    leads = load_leads()
    rec = leads.get(str(chat_id), {})
    if rec.get("stage") in ("start", "done", "verified"):
        context.bot.send_message(
            chat_id,
            text=(
                "Need a hand?\n\n"
                'Add funds at your own pace. When you’re done, type: "Funded".\n'
                "If you have questions, tap “Contact Support” in the menu."
            ),
        )


def _edit_or_send(query, text, reply_markup=None):
    """Helper: prefer editing the callback message; fallback to sending."""
    try:
        query.edit_message_text(text=text, reply_markup=reply_markup, disable_web_page_preview=True)
    except Exception:
        try:
            query.message.reply_text(text=text, reply_markup=reply_markup, disable_web_page_preview=True)
        except Exception:
            pass


def on_button(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    d = q.data
    chat_id = q.message.chat.id

    if d == "onb1":
        tag_lead(chat_id, "start")
        _edit_or_send(
            q,
            "✅ Step 1 — Create Your Vantage Account\n\n"
            f"👉 {VANTAGE_LINK}\n\n"
            'When finished, type: "Done".',
        )
        return

    if d == "track_low":
        tag_lead(chat_id, "track_selected", track="low")
        t = TRACKS["low"]
        _edit_or_send(
            q,
            f"{t['title']}\n\n"
            f"Start date: {t['start_date']}\n"
            f"Starting balance: ${t['starting_balance']}\n"
            f"Style: {t['style']}\n\n"
            "Next: Tap ✅ Start Copying (step-by-step) when you’re ready.\n\n"
            + DISCLAIMER,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Start Copying", callback_data="onb1")],
                                               [InlineKeyboardButton("Back", callback_data="back")]]),
        )
        return

    if d == "track_medium":
        tag_lead(chat_id, "track_selected", track="medium")
        t = TRACKS["medium"]
        _edit_or_send(
            q,
            f"{t['title']}\n\n"
            f"Track record since: {t['start_date']}\n"
            f"Starting balance: ${t['starting_balance']}\n"
            f"Style: {t['style']}\n\n"
            "Next: Tap ✅ Start Copying (step-by-step) when you’re ready.\n\n"
            + DISCLAIMER,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Start Copying", callback_data="onb1")],
                                               [InlineKeyboardButton("Back", callback_data="back")]]),
        )
        return

    if d == "results":
        tag_lead(chat_id, "results")
        _edit_or_send(
            q,
            "📊 Results (overview)\n\n"
            "Medium Risk account started at $500 and is currently around ~$2,500.\n"
            "Verified stats (drawdown, weekly performance, etc.) can be added here once you provide exact numbers.\n\n"
            + DISCLAIMER,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]),
        )
        return

    if d == "risk":
        tag_lead(chat_id, "risk")
        _edit_or_send(
            q,
            "📉 Risk & Drawdown\n\n"
            "Two tracks:\n"
            "• Low Risk: more conservative, smoother swings\n"
            "• Medium Risk: higher tempo, still rule-based\n\n"
            "You stay in control and can pause/stop anytime.\n\n"
            + DISCLAIMER,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]),
        )
        return

    if d == "faq":
        tag_lead(chat_id, "faq")
        lines = ["❓ FAQ\n"]
        for qtxt, atxt in FAQ_ITEMS:
            lines.append(f"• {qtxt}\n{atxt}\n")
        lines.append(DISCLAIMER)
        _edit_or_send(q, "\n".join(lines), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]))
        return

    if d == "copy":
        tag_lead(chat_id, "copied")
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Open Copy Link", url=COPY_LINK)],
                [InlineKeyboardButton("Info Channel", url=CHANNEL_LINK)],
                [InlineKeyboardButton("Back", callback_data="back")],
            ]
        )
        _edit_or_send(
            q,
            "Copy link:\n"
            f"👉 {COPY_LINK}\n\n"
            "If you want, tap the button above to open it directly.",
            reply_markup=kb,
        )
        return

    if d == "agent":
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Open Support", url=SUPPORT_LINK)],
                [InlineKeyboardButton("Back", callback_data="back")],
            ]
        )
        _edit_or_send(
            q,
            "🧾 Support\n\n"
            "Write your message here, or open support using the button below.",
            reply_markup=kb,
        )
        return

    if d == "back":
        _edit_or_send(q, "Back to menu.", reply_markup=main_menu())
        return


def on_text(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    t = (update.message.text or "").strip().lower()

    if t == "done":
        tag_lead(chat_id, "done")
        update.message.reply_text(
            '✅ Step 2 — Verification (KYC)\n\n'
            'Upload your ID + proof of address.\n\n'
            'When ready, type: "Verified".'
        )
        return

    if t == "verified":
        tag_lead(chat_id, "verified")
        update.message.reply_text(
            "✅ Step 3 — Add Funds\n\n"
            "Choose a starting amount you are comfortable with.\n"
            "(Example journey: we started from $500.)\n\n"
            'When complete, type: "Funded".'
        )
        return

if t == "funded":
    tag_lead(chat_id, "funded")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Open Copy Trading", url=COPY_LINK)],
        [InlineKeyboardButton("📣 Info Channel", url=CHANNEL_LINK)],
    ])
    update.message.reply_text(
        "✅ Step 4 — Activate Copy Trading\n\n"
        "Tap the button below to open Copy Trading.\n\n"
        f"{DISCLAIMER}",
        reply_markup=kb,
        disable_web_page_preview=True
    )
    return


    if t in {"/start", "start"}:
        start(update, context)
        return

    update.message.reply_text('I didn’t understand. Use the menu buttons or type /start.')


def stats(update: Update, context: CallbackContext):
    if OWNER_ID and update.effective_user.id != OWNER_ID:
        update.message.reply_text("Stats are restricted.")
        return

    leads = load_leads()
    total = len(leads)
    stages = {}

    for v in leads.values():
        st = v.get("stage", "start")
        stages[st] = stages.get(st, 0) + 1

    # top sources
    sources = {}
    for v in leads.values():
        s = v.get("source")
        if s:
            sources[s] = sources.get(s, 0) + 1

    msg_lines = [f"Leads: {total}"]
    for k in sorted(stages.keys()):
        msg_lines.append(f"{k}: {stages[k]}")
    if sources:
        msg_lines.append("")
        msg_lines.append("Sources:")
        for k in sorted(sources.keys()):
            msg_lines.append(f"{k}: {sources[k]}")

    update.message.reply_text("\n".join(msg_lines))


def main():
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
    
