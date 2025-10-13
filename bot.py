import logging
import json
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
import threading
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

import config

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# --- Fake minimal web server handler ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Telegram bot is running")


def run_fake_webserver():
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    logger.info(f"Starting fake web server on port {port}")
    server.serve_forever()


# --- Telegram Bot code below ---

def json_serialize_user(user, group_title=None, event="unknown"):
    """Serialize user info into dict with timestamp and event info."""
    return {
        "user_id": user.id,
        "username": user.username,
        "name": f"{user.first_name or ''} {user.last_name or ''}".strip(),
        "event": event,
        "group": group_title,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


async def store_user_data(context: ContextTypes.DEFAULT_TYPE, user_data: dict):
    """Saves user data as a JSON message in the data storage group."""
    text = "[USER_DATA]\n" + json.dumps(user_data, ensure_ascii=False)
    try:
        await context.bot.send_message(chat_id=config.DATA_GROUP_ID, text=text)
    except Exception as e:
        logger.error(f"Failed to store user data: {e}")


# Handler for new members joining
async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for user in update.message.new_chat_members:
        user_data = json_serialize_user(user, update.effective_chat.title, "joined")
        await store_user_data(context, user_data)


# Handler for members leaving
async def member_left(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.left_chat_member
    if user:
        user_data = json_serialize_user(user, update.effective_chat.title, "left")
        await store_user_data(context, user_data)


# Handler for user profile changes detected on messages
async def track_profile_changes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # When user sends a message, log current username and name for change tracking
    user = update.effective_user
    chat_title = update.effective_chat.title if update.effective_chat else None
    if user:
        user_data = json_serialize_user(user, chat_title, "profile_update")
        await store_user_data(context, user_data)


# Command handler to fetch user info by user_id
async def userinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /userinfo <user_id>")
        return
    user_id = context.args[0]
    if not user_id.isdigit():
        await update.message.reply_text("User ID must be a number.")
        return

    user_id = int(user_id)
    # Search recent messages in DATA_GROUP_ID group for user data matching user_id
    messages = []
    try:
        async for message in context.bot.get_chat_history(config.DATA_GROUP_ID, limit=500):
            if message.text and message.text.startswith("[USER_DATA]"):
                try:
                    data = json.loads(message.text.split("\n", 1)[1])
                    if data.get("user_id") == user_id:
                        messages.append(data)
                except Exception:
                    continue
    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        await update.message.reply_text("Failed to fetch user data.")
        return

    if not messages:
        await update.message.reply_text("No data found for this user.")
        return

    # Compose reply summarizing user info and count of groups found
    username = messages[-1].get("username", "None")
    name = messages[-1].get("name", "None")
    groups = {m.get("group") for m in messages if m.get("group")}
    groups.discard(None)
    group_count = len(groups)

    reply = (
        "Human found!\n"
        f"Telegram ID: {user_id}\n"
        f"Username: {username}\n"
        f"Name: {name}\n"
        f"Number of groups found: {group_count}\n"
        f"Groups: {', '.join(groups) if groups else 'None'}"
    )
    await update.message.reply_text(reply)


def main():
    # Start fake web server in background thread
    threading.Thread(target=run_fake_webserver, daemon=True).start()

    application = (
        ApplicationBuilder()
        .token(config.BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    # Handlers for join, leave, profile update and commands
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, member_left))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track_profile_changes))
    application.add_handler(CommandHandler("userinfo", userinfo_command))

    application.run_polling()


if __name__ == "__main__":
    main()
