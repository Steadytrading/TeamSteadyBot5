# -*- coding: utf-8 -*-
"""
Team Steady – Telegram Bot (EN, Corporate) – Enhanced v2
- Lead tagging on /start (writes to leads.json)
- Funnel stage tracking (done/verified/funded/copied)
- Auto follow-ups via JobQueue (30m, 24h, 72h)
- /stats for owner to see simple metrics
Requires: python-telegram-bot==13.15
"""
import os, json, logging, time
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8515532779:AAEMYpgKLFG_RTa-gB4b0V7T0ZBurB1tuWk')
VANTAGE_LINK = 'https://www.vantagemarkets.com/open-live-account/?affid=MjMxNDQ0MzY=&gad_source=1&gad_campaignid=23494365984&gbraid=0AAAABCsAuaye6WQIqKss-cJVC3PS6OGm2&gclid=Cj0KCQiAy6vMBhDCARIsAK8rOgkm1I-nxMmY7LlohkY2Eg_lvTgCkY81ol1DgxQne7lSWlNLJ2Wdj8YaAvZCEALw_wcB'
COPY_LINK   = 'https://vantageapp.onelink.me/qaPD?af_xp=custom&pid=CopyTrading_Offer&af_web_dp=https%3A%2F%2Fsecure.vantagemarkets.com%2FcopyTrading%2Fdiscover%2FdiscoverDetail&deep_link_value=DPTCPDWZWAIAA=='
CHANNEL_LINK= 'https://t.me/steadytradingteam'
SUPPORT_LINK= 'https://t.me/steadysupport'
LOGO_FILE   = os.path.join(os.path.dirname(__file__), 'logo.png')
LEADS_FILE  = os.path.join(os.path.dirname(__file__), 'leads.json')
DISCLAIMER  = 'This is not financial advice. Trading involves risk; past performance does not guarantee future results.'
OWNER_ID    = int(os.getenv('BOT_OWNER_ID', '0'))  # optional: set your Telegram user id to restrict /stats

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('teamsteady')

# --- Persistence helpers ---

def load_leads():
    if not os.path.exists(LEADS_FILE):
        return {}
    try:
        with open(LEADS_FILE,'r',encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_leads(data):
    with open(LEADS_FILE,'w',encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# lead structure: { str(chat_id): {"first_seen":iso, "stage":"start|done|verified|funded|copied", "last_touch":iso } }

# --- UI ---

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('1️⃣ Get Started', callback_data='onb1')],
        [InlineKeyboardButton('2️⃣ How Copy Trading Works', callback_data='info')],
        [InlineKeyboardButton('3️⃣ Copy Link', callback_data='copy')],
        [InlineKeyboardButton('4️⃣ Contact Support', callback_data='agent')]
    ])

WELCOME = (
    'Welcome to Team Steady!\n\n'
    'Copy a professional strategy automatically on Vantage with a clear, guided onboarding.\n'
    'You stay fully in control and can pause anytime.\n\n' + DISCLAIMER
)

# --- Lead tagging ---

def tag_lead(chat_id, stage='start'):
    leads = load_leads()
    now = datetime.utcnow().isoformat()
    rec = leads.get(str(chat_id), {"first_seen": now, "stage": stage, "last_touch": now})
    rec["stage"] = stage or rec.get("stage","start")
    rec["last_touch"] = now
    leads[str(chat_id)] = rec
    save_leads(leads)

# --- Handlers ---

def start(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    tag_lead(chat_id, 'start')
    try:
        if os.path.exists(LOGO_FILE):
            update.message.reply_photo(open(LOGO_FILE,'rb'), caption=WELCOME)
        else:
            update.message.reply_text(WELCOME)
    except Exception:
        update.message.reply_text(WELCOME)
    update.message.reply_text('Choose an option below:', reply_markup=main_menu())

    # schedule follow-ups
    # 30 minutes
    context.job_queue.run_once(followup_30m, 30*60, context=chat_id, name=f"fu30_{chat_id}")
    # 24 hours
    context.job_queue.run_once(followup_24h, 24*60*60, context=chat_id, name=f"fu24_{chat_id}")
    # 72 hours
    context.job_queue.run_once(followup_72h, 72*60*60, context=chat_id, name=f"fu72_{chat_id}")


def followup_30m(context: CallbackContext):
    chat_id = context.job.context
    leads = load_leads(); rec = leads.get(str(chat_id),{})
    if rec.get('stage') == 'start':
        context.bot.send_message(chat_id, text=(
            'Quick reminder: creating your Vantage account is the first step.\n\n'
            f'👉 {VANTAGE_LINK}\n\nType "Done" when finished.'
        ))

def followup_24h(context: CallbackContext):
    chat_id = context.job.context
    leads = load_leads(); rec = leads.get(str(chat_id),{})
    if rec.get('stage') in ('start','done'):
        context.bot.send_message(chat_id, text=(
            'How is it going? Once verification (KYC) is completed, you are one step from copy trading.\nType "Verified" when ready.'
        ))

def followup_72h(context: CallbackContext):
    chat_id = context.job.context
    leads = load_leads(); rec = leads.get(str(chat_id),{})
    if rec.get('stage') in ('start','done','verified'):
        context.bot.send_message(chat_id, text=(
            'Need a hand? Add funds at your own pace. When you are done, type "Funded".\nIf you have questions, tap "Contact Support" in the menu.'
        ))


def on_button(update: Update, context: CallbackContext):
    q = update.callback_query; q.answer(); d = q.data; chat_id=q.message.chat.id
    if d == 'onb1':
        tag_lead(chat_id, 'start')
        q.edit_message_text('Step 1 — Create Your Vantage Account\n\n👉 ' + VANTAGE_LINK + '\n\nType "Done" when finished.')
        return
    if d == 'info':
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton('Get Started', callback_data='onb1')],
            [InlineKeyboardButton('Copy Link', callback_data='copy')],
            [InlineKeyboardButton('Back', callback_data='back')]
        ])
        q.edit_message_text('Copy trading mirrors our trades automatically. You control your capital and can pause anytime.\n\n' + DISCLAIMER, reply_markup=kb)
        return
    if d == 'copy':
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton('Get Started', callback_data='onb1')],
            [InlineKeyboardButton('Info Channel', url=CHANNEL_LINK)],
            [InlineKeyboardButton('Back', callback_data='back')]
        ])
        tag_lead(chat_id, 'copied')
        q.edit_message_text('Copy link:\n👉 ' + COPY_LINK + '\n\nNeed help? Choose Get Started.', reply_markup=kb)
        return
    if d == 'agent':
        kb = InlineKeyboardMarkup([[InlineKeyboardButton('Open Support', url=SUPPORT_LINK)], [InlineKeyboardButton('Back', callback_data='back')]])
        q.edit_message_text('Write your message here or open support. We answer as soon as possible.', reply_markup=kb)
        return
    if d == 'back':
        q.edit_message_text('Back to menu.', reply_markup=main_menu())
        return


def on_text(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    t = (update.message.text or '').strip().lower()
    if t == 'done':
        tag_lead(chat_id, 'done')
        update.message.reply_text('Step 2 — Verification (KYC)\n\nUpload your ID and proof of address. Type "Verified" when ready.')
        return
    if t == 'verified':
        tag_lead(chat_id, 'verified')
        update.message.reply_text('Step 3 — Add Funds\n\nChoose a starting amount you are comfortable with. (We start from $500). Type "Funded" when complete.')
        return
    if t == 'funded':
        tag_lead(chat_id, 'funded')
        update.message.reply_text('Step 4 — Activate Copy Trading\n\n👉 ' + COPY_LINK + '\nPress "Copy". When ready, you gain access to our information channel:')
        update.message.reply_text(CHANNEL_LINK)
        return
    if t in {'/start','start'}:
        start(update, context)
        return
    update.message.reply_text('I did not understand. Choose a menu option or type /start.')


def stats(update: Update, context: CallbackContext):
    if OWNER_ID and update.effective_user.id != OWNER_ID:
        update.message.reply_text('Stats are restricted.')
        return
    leads = load_leads()
    total = len(leads)
    stages = {'start':0,'done':0,'verified':0,'funded':0,'copied':0}
    for v in leads.values():
        stages[v.get('stage','start')] = stages.get(v.get('stage','start'),0)+1
    msg = (
        f"Leads: {total}\n"
        f"Start: {stages.get('start',0)}\n"
        f"Done: {stages.get('done',0)}\n"
        f"Verified: {stages.get('verified',0)}\n"
        f"Funded: {stages.get('funded',0)}\n"
        f"Copied: {stages.get('copied',0)}\n"
    )
    update.message.reply_text(msg)


def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CommandHandler('stats', stats))
    dp.add_handler(CallbackQueryHandler(on_button))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, on_text))
    # JobQueue will handle follow-ups as long as the process is running
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
