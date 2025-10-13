from fastapi import FastAPI, Request
from pydantic import BaseModel
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler
import os
import logging
import asyncio

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_GROUP_ID = os.getenv("DATABASE_GROUP_ID")  # Telegram group ID for storing data

bot = Bot(token=BOT_TOKEN)
app = FastAPI()

# Create Dispatcher for handling updates
dp = Dispatcher(bot=bot, update_queue=asyncio.Queue(), use_context=True)

class TelegramUpdate(BaseModel):
    update_id: int
    message: dict = None
    edited_message: dict = None
    channel_post: dict = None
    edited_channel_post: dict = None

@app.post("/webhook")
async def telegram_webhook(update: TelegramUpdate, request: Request):
    telegram_update = Update.de_json(update.dict(), bot)
    dp.process_update(telegram_update)
    return {"status": "ok"}

# Command handler example: /start
def start(update, context):
    update.message.reply_text("Hello! I am Scanrobot, your Telegram bot.")

# Store user info command example: /store_me
def store_user_info(update, context):
    user = update.message.from_user
    user_info = (
        f"UserID: {user.id}, "
        f"Name: {user.first_name} {user.last_name or ''}, "
        f"Username: @{user.username or 'N/A'}"
    )
    # Store info in the database group as a message
    try:
        bot.send_message(chat_id=DATABASE_GROUP_ID, text=user_info)
        update.message.reply_text("Your info has been stored in the database group.")
    except Exception as e:
        logger.error(f"Error storing info: {e}")
        update.message.reply_text("Failed to store your info.")

dp.add_handler(CommandHandler("start", start))
dp.add_handler(CommandHandler("store_me", store_user_info))

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), log_level="info")
