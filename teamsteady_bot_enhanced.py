import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

BRAND_NAME = os.getenv("BRAND_NAME", "MCM Trading")
COPY_TRADING_LINK = os.getenv("COPY_TRADING_LINK", "https://vantage.example")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/examplechannel")
SUPPORT_LINK = os.getenv("SUPPORT_LINK", "https://t.me/example_support")


def main_menu():
    keyboard = [
        [InlineKeyboardButton("🚀 Start Copy Trading", url=COPY_TRADING_LINK)],
        [InlineKeyboardButton("📣 Join Telegram Channel", url=CHANNEL_LINK)],
        [InlineKeyboardButton("❓ FAQ", callback_data="faq")],
        [InlineKeyboardButton("⚠️ Risk Disclaimer", callback_data="risk")],
        [InlineKeyboardButton("💬 Support", url=SUPPORT_LINK)],
    ]
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = f"""
Welcome to *{BRAND_NAME}*

We provide structured gold (XAUUSD) copy trading.

Our strategy allows you to automatically copy trades directly to your Vantage account.

Steps:

1️⃣ Open a Vantage account  
2️⃣ Click copy strategy  
3️⃣ Trades will copy automatically  

Press the button below to begin.
"""

    await update.message.reply_text(
        text,
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    if query.data == "faq":

        text = f"""
❓ *FAQ*

How does it work?

You connect your Vantage account to our strategy.

When we open a trade, it is automatically copied to your account.

You remain in full control of your funds.

You can stop copying at any time.
"""

        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu())

    elif query.data == "risk":

        text = """
⚠️ *Risk Disclaimer*

Trading leveraged products such as forex and gold carries a high level of risk.

Past performance does not guarantee future results.

Only trade with capital you can afford to lose.
"""

        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu())


def main():

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))

    print("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()
