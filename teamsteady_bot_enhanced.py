# -*- coding: utf-8 -*-
"""
Team Steady – Telegram Bot (EN) – Enhanced v3.1 (stable + human + tracking)
- python-telegram-bot==13.15
- Lead tagging + funnel tracking (leads.json)
- Deep link source tracking: t.me/TeamSteadybot?start=meta / ?start=tiktok
- Track selection: Low Risk vs Medium Risk
- Auto follow-ups (30m, 24h, 72h) without duplicates
- /stats (optional restricted by BOT_OWNER_ID)

IMPORTANT:
- Set TELEGRAM_BOT_TOKEN in Railway -> Variables
- leads.json is file-based; consider DB later for persistence across restarts
"""

import os
import json
import logging
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

# -------------------------
# Config (Railway Variables)
# -------------------------

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN env var (set it in Railway -> Variables).")

# Optional: restrict /stats to your Telegram user id (numeric)
OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEADS_FILE = os.path.join(BASE_DIR, "leads.json")

# Prefer logo_icon.png if present; fallback to logo.png; otherwise no logo
LOGO_FILE = os.path.join(BASE_DIR, "logo_icon.png")
if not os.path.exists(LOGO_FILE):
    LOGO_FILE = os.path.join(BASE_DIR, "logo.png")

# Links
VANTAGE_LINK = "https://www.vantagemarkets.com/open-live-account/?affid=MjMxNDQ0MzY=&gad_source=1&gad_campaignid=23494365984&gbraid=0AAAABCsAuaye6WQIqKss-cJVC3PS6OGm2&gclid=Cj0KCQiAy6vMBhDCARIsAK8rOgkm1I-nxMmY7LlohkY2Eg_lvTgCkY81ol1DgxQne7lSWlNLJ2Wdj8YaAvZCEALw_wcB"
COPY_LINK = "https://vantageapp.onelink.me/qaPD?af_xp=custom&pid=CopyTrading_Offer&af_web_dp=https%3A%2F%2Fsecure.vantagemarkets.com%2FcopyTrading%2Fdiscover%2FdiscoverDetail&deep_link_value=DPTCPDWZWAIAA=="
CHANNEL_LINK = "https://t.me/steadytradingteam"
SUPPORT_LINK = "https://t.me/steadysupport"

DISCLAIMER = "Trading involves risk. Past performance does not guarantee future results. This is not financial advice."

# Tracks (edit these whenever you want)
TRACKS = {
    "low": {
        "title": "Low Risk (starting Monday)",
        "start_date": "2026-02-16",   # adjust if needed
        "starting_balance": 883,
        "style": "More conservative approach focused on capital preservation and smoother swings.",
    },
    "medium": {
        "title": "Medium Risk (track record since Jan 12)",
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("teamsteady")


# -------------------------
# Persistence
# -------------------------

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


def tag_lead(chat_id, stage="start", source=None, name=None, track=None):
    """
    lead structure:
    {
      "123": {
        "first_seen": "...",
        "last_touch": "...",
        "stage": "start|done|verified|funded|...",
        "source": "meta|tiktok|organic",
        "name": "John",
        "track": "low|medium"
      }
    }
    """
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


# -------------------------
# UI helpers
# -------------------------

def main_menu():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Start Copying (step-by-step)", callback_data="onb1")],
            [InlineKeyboardButton("🟢 Low Risk Track", callback_data="track_low")],
            [InlineKeyboardButton("🟠 Medium Risk Track", callback_data="track_medium")],
            [InlineKeyboardButton("📊 Results (journey overview)", callback_data="results")],
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
        "I trade XAUUSD (Gold) with a simple goal: protect capital first, grow second.\n"
        "You get a clear setup guide + transparent updates.\n\n"
        "Choose a track below (Low Risk or Medium Risk), then tap ✅ Start Copying.\n\n"
        f"{DISCLAIMER}"
    )


def _edit_or_send(query, text, reply_markup=None):
    """Prefer editing callback message; fallback to sending."""
    try:
        query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    except Exception:
        try:
            query.message.reply_text(
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
        except Exception:
            pass


def remove_followups(job_queue, chat_id: int):
    """Avoid duplicate reminders if user runs /start multiple times."""
    names = [f"fu30_{chat_id}", f"fu24_{chat_id}", f"fu72_{chat_id}"]
    for n in names:
        for job in job_queue.get_jobs_by_name(n):
            job.schedule_removal()


# -------------------------
# Follow-ups
# -------------------------

def followup_30m(context: CallbackContext):
    chat_id = context.job.context
    rec = load_leads().get(str(chat_id), {})
    if rec.get("stage") == "start":
        context.bot.send_message(
            chat_id,
            text=(
                "Quick reminder 👇\n\n"
                "Step 1 is creating your Vantage account:\n"
                f"👉 {VANTAGE_LINK}\n\n"
                'When you’re done, type: "Done"'
            ),
            disable_web_page_preview=True,
        )


def followup_24h(context: CallbackContext):
    chat_id = context.job.context
    rec = load_leads().get(str(chat_id), {})
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
    rec = load_leads().get(str(chat_id), {})
    if rec.get("stage") in ("start", "done", "verified"):
        context.bot.send_message(
            chat_id,
            text=(
                "Need a hand?\n\n"
                'Add funds at your own pace. When you’re done, type: "Funded".\n'
                "If you have questions, tap “Contact Support” in the menu."
            ),
        )


# -------------------------
# Handlers
# -------------------------

def start(update: Update, context: CallbackContext):
    user = update.effective_user
    chat_id = update.effective_chat.id

    # Deep link source tracking: /start meta OR /start tiktok
    source = None
    if getattr(context, "args", None) and len(context.args) > 0:
        source = (context.args[0] or "").strip().lower()[:40] or None
    if not source:
        source = "organic"

    tag_lead(chat_id, "start", source=source, name=getattr(user, "first_name", None))
    welcome = build_welcome(getattr(user, "first_name", ""))

    # Send logo (optional) + welcome
    try:
        if os.path.exists(LOGO_FILE):
            with open(LOGO_FILE, "rb") as f:
                update.message.reply_photo(photo=f, caption=welcome)
        else:
            update.message.reply_text(welcome)
    except Exception:
        update.message.reply_text(welcome)

    update.message.reply_text("Choose an option below:", reply_markup=main_menu())

    # Avoid duplicate reminders
    remove_followups(context.job_queue, chat_id)

    # Schedule follow-ups
    context.job_queue.run_once(followup_30m, 30 * 60, context=chat_id, name=f"fu30_{chat_id}")
    context.job_queue.run_once(followup_24h, 24 * 60 * 60, context=chat_id, name=f"fu24_{chat_id}")
    context.job_queue.run_once(followup_72h, 72 * 60 * 60, context=chat_id, name=f"fu72_{chat_id}")


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
            'When finished, type: "Done".\n\n'
            + DISCLAIMER,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]),
        )
        return

    if d == "track_low":
        tag_lead(chat_id, "track_selected", track="low")
        t = TRACKS["low"]
        _edit_or_send(
            q,
            f"🟢 {t['title']}\n\n"
            f"Start date: {t['start_date']}\n"
            f"Starting balance: ${t['starting_balance']}\n"
            f"Style: {t['style']}\n\n"
            "Next: Tap ✅ Start Copying (step-by-step) when you’re ready.\n\n"
            + DISCLAIMER,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("✅ Start Copying", callback_data="onb1")],
                    [InlineKeyboardButton("Back", callback_data="back")],
                ]
            ),
        )
        return

    if d == "track_medium":
        tag_lead(chat_id, "track_selected", track="medium")
        t = TRACKS["medium"]
        _edit_or_send(
            q,
            f"🟠 {t['title']}\n\n"
            f"Track record since: {t['start_date']}\n"
            f"Starting balance: ${t['starting_balance']}\n"
            f"Style: {t['style']}\n\n"
            "Next: Tap ✅ Start Copying (step-by-step) when you’re ready.\n\n"
            + DISCLAIMER,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("✅ Start Copying", callback_data="onb1")],
                    [InlineKeyboardButton("Back", callback_data="back")],
                ]
            ),
        )
        return

    if d == "results":
        tag_lead(chat_id, "results")
        _edit_or_send(
            q,
            "📊 Results (journey overview)\n\n"
            "Medium Risk account:\n"
            "• Started: $500\n"
            "• Current: ~ $2,500 (approx)\n"
            "• Since: Jan 12\n\n"
            "Low Risk account starts Monday (more conservative).\n\n"
            "Verified stats (drawdown, weekly performance, etc.) can be added once you provide exact numbers.\n\n"
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
        _edit_or_send(
            q,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]]),
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
            "Write your question here, or open support using the button below.\n\n"
            + DISCLAIMER,
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
            "✅ Step 2 — Verification (KYC)\n\n"
            "Upload your ID + proof of address.\n\n"
            'When ready, type: "Verified".'
        )
        return

    if t == "verified":
        tag_lead(chat_id, "verified")
        update.message.reply_text(
            "✅ Step 3 — Add Funds\n\n"
            "Choose a starting amount you are comfortable with.\n"
            "(Journey example: started from $500.)\n\n"
            'When complete, type: "Funded".\n\n'
            + DISCLAIMER
        )
        return

    if t == "funded":
        tag_lead(chat_id, "funded")
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🚀 Open Copy Trading", url=COPY_LINK)],
                [InlineKeyboardButton("📣 Info Channel", url=CHANNEL_LINK)],
                [InlineKeyboardButton("Back to Menu", callback_data="back")],
            ]
        )
        update.message.reply_text(
            "✅ Step 4 — Activate Copy Trading\n\n"
            "Tap the button below to open Copy Trading.\n\n"
            + DISCLAIMER,
            reply_markup=kb,
            disable_web_page_preview=True,
        )
        return

    # convenience
    if t in ("/start", "start"):
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
    sources = {}
    tracks = {}

    for v in leads.values():
        st = v.get("stage", "start")
        stages[st] = stages.get(st, 0) + 1
        s = v.get("source")
        if s:
            sources[s] = sources.get(s, 0) + 1
        tr = v.get("track")
        if tr:
            tracks[tr] = tracks.get(tr, 0) + 1

    msg = [f"Leads: {total}", ""]
    msg.append("Stages:")
    for k in sorted(stages.keys()):
        msg.append(f"- {k}: {stages[k]}")

    if sources:
        msg.append("")
        msg.append("Sources:")
        for k in sorted(sources.keys()):
            msg.append(f"- {k}: {sources[k]}")

    if tracks:
        msg.append("")
        msg.append("Tracks:")
        for k in sorted(tracks.keys()):
            msg.append(f"- {k}: {tracks[k]}")

    update.message.reply_text("\n".join(msg))


# -------------------------
# Main
# -------------------------

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
