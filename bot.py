import logging
import json
from datetime import datetime
from telegram import Update, InputFile
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
import tempfile

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

# --- Permission system for bot DP changing ---
BOT_OWNER_ID = 5451324394  # <-- Replace with your Telegram user ID here
allowed_users = set()

async def allowuser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != BOT_OWNER_ID:
        await update.message.reply_text("❌ Only the bot owner can allow users.")
        return
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /allowuser <user_id>")
        return
    user_id = int(context.args[0])
    allowed_users.add(user_id)
    await update.message.reply_text(f"✅ User `{user_id}` is now allowed to change the bot DP.", parse_mode="Markdown")

async def disallowuser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != BOT_OWNER_ID:
        await update.message.reply_text("❌ Only the bot owner can disallow users.")
        return
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /disallowuser <user_id>")
        return
    user_id = int(context.args[0])
    if user_id in allowed_users:
        allowed_users.remove(user_id)
        await update.message.reply_text(f"❌ User `{user_id}` is no longer allowed to change the bot DP.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"ℹ️ User `{user_id}` was not previously allowed.", parse_mode="Markdown")

async def setbotdp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != BOT_OWNER_ID and user_id not in allowed_users:
        await update.message.reply_text("❌ You do not have permission to change the bot DP.")
        return

    photo = None
    if update.message.reply_to_message and update.message.reply_to_message.photo:
        photo = update.message.reply_to_message.photo[-1]
    elif update.message.photo:
        photo = update.message.photo[-1]
    else:
        await update.message.reply_text("⚠️ Please send or reply to an image with /setbotdp to change bot profile photo.")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, "bot_dp.jpg")
        file = await photo.get_file()
        await file.download_to_drive(file_path)

        try:
            with open(file_path, "rb") as photo_file:
                await context.bot.set_my_profile_photo(photo=InputFile(photo_file))
            await update.message.reply_text("✅ Bot profile photo updated successfully!")
        except Exception as e:
            logger.error(f"Failed to set bot profile photo: {e}")
            await update.message.reply_text("❌ Failed to update bot profile photo.")

# --- Existing bot tracking features ---

def json_serialize_user(user, group_title=None, event="unknown"):
    return {
        "user_id": user.id,
        "username": user.username,
        "name": f"{user.first_name or ''} {user.last_name or ''}".strip(),
        "event": event,
        "group": group_title,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

async def store_user_data(context: ContextTypes.DEFAULT_TYPE, user_data: dict):
    text = "[USER_DATA]\n" + json.dumps(user_data, ensure_ascii=False)
    try:
        await context.bot.send_message(chat_id=config.DATA_GROUP_ID, text=text)
    except Exception as e:
        logger.error(f"Failed to store user data: {e}")

async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for user in update.message.new_chat_members:
        user_data = json_serialize_user(user, update.effective_chat.title, "joined")
        await store_user_data(context, user_data)

async def member_left(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.left_chat_member
    if user:
        user_data = json_serialize_user(user, update.effective_chat.title, "left")
        await store_user_data(context, user_data)

async def track_profile_changes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_title = update.effective_chat.title if update.effective_chat else None
    if user:
        user_data = json_serialize_user(user, chat_title, "profile_update")
        await store_user_data(context, user_data)

async def userinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /userinfo <user_id>")
        return
    user_id_str = context.args[0]
    if not user_id_str.isdigit():
        await update.message.reply_text("User ID must be a number.")
        return

    user_id = int(user_id_str)
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

    username = messages[-1].get("username", "None")
    name = messages[-1].get("name", "None")
    groups = {m.get("group") for m in messages if m.get("group")}
    groups.discard(None)
    group_count = len(groups)

    reply = (
        f"*🤖 User Information*\n"
        f"• *Telegram ID:* `{user_id}`\n"
        f"• *Username:* @{username if username != 'None' else 'N/A'}\n"
        f"• *Name:* {name if name else 'N/A'}\n"
        f"• *Number of Groups:* {group_count}\n"
        f"• *Groups:*\n"
    )
    for group in groups:
        reply += f"    - {group}\n"

    await update.message.reply_text(reply, parse_mode="Markdown")

async def groupcount_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /groupcount <user_id>")
        return
    user_id_str = context.args[0]
    if not user_id_str.isdigit():
        await update.message.reply_text("User ID must be a number.")
        return
    user_id = int(user_id_str)

    groups = set()
    try:
        async for message in context.bot.get_chat_history(config.DATA_GROUP_ID, limit=500):
            if message.text and message.text.startswith("[USER_DATA]"):
                try:
                    data = json.loads(message.text.split("\n",1)[1])
                    if data.get("user_id") == user_id and data.get("group"):
                        groups.add(data.get("group"))
                except:
                    continue
    except Exception as e:
        await update.message.reply_text("Failed to fetch group data.")
        return

    await update.message.reply_text(f"User {user_id} found in {len(groups)} groups.")

async def grouplist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /grouplist <user_id>")
        return
    user_id_str = context.args[0]
    if not user_id_str.isdigit():
        await update.message.reply_text("User ID must be a number.")
        return
    user_id = int(user_id_str)

    groups = set()
    try:
        async for message in context.bot.get_chat_history(config.DATA_GROUP_ID, limit=500):
            if message.text and message.text.startswith("[USER_DATA]"):
                try:
                    data = json.loads(message.text.split("\n",1)[1])
                    if data.get("user_id") == user_id and data.get("group"):
                        groups.add(data.get("group"))
                except:
                    continue
    except Exception as e:
        await update.message.reply_text("Failed to fetch group list.")
        return

    if not groups:
        await update.message.reply_text("No groups found for this user.")
        return

    reply_text = f"User {user_id} is in the following groups:\n" + "\n".join(groups)
    await update.message.reply_text(reply_text)

# Fancy help command with emojis and descriptions
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "*🤖 Bot Commands and Features*\n\n"
        "• /userinfo <user_id> - Get detailed info about a user including username, name, and groups.\n"
        "• /groupcount <user_id> - Show the number of groups a user is found in.\n"
        "• /grouplist <user_id> - List all groups where the user was detected.\n"
        "• /setbotdp - Change the bot's profile picture by sending or replying to a photo.\n"
        "• /allowuser <user_id> - (Owner only) Allow a user to change the bot's profile picture.\n"
        "• /disallowuser <user_id> - (Owner only) Revoke a user's permission to change the bot DP.\n"
        "\n_Each command requires correct arguments. Only authorized users can change the bot DP._"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

def main():
    threading.Thread(target=run_fake_webserver, daemon=True).start()

    application = (
        ApplicationBuilder()
        .token(config.BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    # Permissions and DP change handlers
    application.add_handler(CommandHandler("allowuser", allowuser_command))
    application.add_handler(CommandHandler("disallowuser", disallowuser_command))
    application.add_handler(CommandHandler("setbotdp", setbotdp_command))

    # Tracking handlers
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, member_left))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track_profile_changes))

    # Info commands
    application.add_handler(CommandHandler("userinfo", userinfo_command))
    application.add_handler(CommandHandler("groupcount", groupcount_command))
    application.add_handler(CommandHandler("grouplist", grouplist_command))

    # Help command
    application.add_handler(CommandHandler("help", help_command))

    application.run_polling()

if __name__ == "__main__":
    main()
