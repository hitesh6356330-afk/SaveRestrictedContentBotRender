import logging
import json
from datetime import datetime
from telegram import Update, User, Chat
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


# Fake minimal web server handler for Render
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


BOT_OWNER_ID = 5451324394  # Your Telegram user ID

# In-memory datastore: user_id -> user data dict
tracked_users = {}


def now_iso():
    return datetime.utcnow().isoformat() + "Z"


def user_full_name(user: User):
    return f"{user.first_name or ''} {user.last_name or ''}".strip()


def add_group_if_new(user_data, chat: Chat):
    for g in user_data.get("groups", []):
        if g['group_id'] == chat.id:
            return
    user_data.setdefault("groups", []).append({
        "group_id": chat.id,
        "group_name": chat.title or "",
        "join_time": now_iso(),
        "leave_time": None
    })


def update_name_history(user_data, new_name: str):
    history = user_data.setdefault("name_history", [])
    if not history or history[-1]["name"] != new_name:
        history.append({"name": new_name, "timestamp": now_iso()})


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot is up and running! Send /help to see commands.")


async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Test command received!")


async def debug_echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text:
        await update.message.reply_text(f"Echo: {update.message.text}")


async def scan_group_members(chat, context: ContextTypes.DEFAULT_TYPE):
    """Example: Scan admins and store as members (extend as needed)"""
    logger.info(f"Scanning members in group {chat.title} ({chat.id})")
    try:
        admins = await context.bot.get_chat_administrators(chat.id)
        for admin in admins:
            user = admin.user
            user_data = tracked_users.setdefault(user.id, {
                "username": user.username,
                "user_id": user.id,
                "profile_photo_changes": [],
                "last_seen": None,
                "groups": [],
                "name_history": [],
                "join_leave_history": []
            })
            add_group_if_new(user_data, chat)
            update_name_history(user_data, user_full_name(user))
        logger.info(f"Scanned {len(admins)} admins in {chat.title}")
        await context.bot.send_message(chat.id, f"Scanned {len(admins)} admins in this group for tracking.")
    except Exception as e:
        logger.error(f"Error scanning group members: {e}")


async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("This command can only be used in groups.")
        return
    await scan_group_members(chat, context)


async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    for user in update.message.new_chat_members:
        user_data = tracked_users.setdefault(user.id, {
            "username": user.username,
            "user_id": user.id,
            "profile_photo_changes": [],
            "last_seen": None,
            "groups": [],
            "name_history": [],
            "join_leave_history": []
        })
        add_group_if_new(user_data, chat)
        update_name_history(user_data, user_full_name(user))
        user_data.setdefault("join_leave_history", []).append({
            "event": "joined",
            "group_id": chat.id,
            "group_name": chat.title or "",
            "timestamp": now_iso()
        })
        await context.bot.send_message(chat.id, f"Tracking started for new user {user_full_name(user)} ({user.id})")


async def member_left(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.message.left_chat_member
    if user and user.id in tracked_users:
        user_data = tracked_users[user.id]
        for g in user_data.get("groups", []):
            if g["group_id"] == chat.id and g.get("leave_time") is None:
                g["leave_time"] = now_iso()
        user_data.setdefault("join_leave_history", []).append({
            "event": "left",
            "group_id": chat.id,
            "group_name": chat.title or "",
            "timestamp": now_iso()
        })
        await context.bot.send_message(chat.id, f"User {user_full_name(user)} ({user.id}) left the group. Tracking updated.")


async def track_profile_changes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user and user.id in tracked_users:
        user_data = tracked_users[user.id]
        new_name = user_full_name(user)
        update_name_history(user_data, new_name)
        user_data["username"] = user.username
        user_data["last_seen"] = now_iso()


async def userinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /userinfo <user_id>")
        return
    try:
        user_id = int(context.args[0])
    except:
        await update.message.reply_text("User ID must be a number.")
        return
    user_data = tracked_users.get(user_id)
    if not user_data:
        await update.message.reply_text(f"No tracked data for user ID {user_id}")
        return

    msg = f"📄 User Info for ID {user_id}:\n"
    msg += f"Username: @{user_data.get('username', 'N/A')}\n"
    msg += "Name history:\n"
    for h in user_data.get("name_history", []):
        msg += f"  - {h['name']} (at {h['timestamp']})\n"
    msg += "Groups:\n"
    for g in user_data.get("groups", []):
        msg += f"  - {g.get('group_name')} (Joined: {g.get('join_time')}, Left: {g.get('leave_time') or 'Still member'})\n"
    msg += "Join/Leave History:\n"
    for ev in user_data.get("join_leave_history", []):
        msg += f"  - {ev['event'].capitalize()} {ev.get('group_name')} at {ev['timestamp']}\n"
    msg += f"Last Seen (message/activity): {user_data.get('last_seen') or 'Unknown'}\n"

    await update.message.reply_text(msg)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 Bot Commands and Features:\n\n"
        "/start - Start and test bot responsiveness\n"
        "/help - Show this help message\n"
        "/test - Test command\n"
        "/scan - Scan current group members and track them (group only)\n"
        "/userinfo <user_id> - Show tracked info for user\n"
        "\nBot tracks joins, leaves, and name changes after joining groups."
    )
    await update.message.reply_text(help_text)


def main():
    threading.Thread(target=run_fake_webserver, daemon=True).start()

    application = (ApplicationBuilder()
                   .token(config.BOT_TOKEN)
                   .concurrent_updates(True)
                   .build())

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(CommandHandler("userinfo", userinfo_command))

    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, member_left))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track_profile_changes))

    # Echo for debugging messages
    async def debug_echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.text:
            await update.message.reply_text(f"Echo: {update.message.text}")

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, debug_echo))

    application.run_polling()


if __name__ == "__main__":
    main()
