import logging
import json
import io
import threading
from datetime import datetime
from telegram import Update, User
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.error import TelegramError
from http.server import BaseHTTPRequestHandler, HTTPServer
import matplotlib.pyplot as plt
import os

import config  # Your config.py must contain BOT_TOKEN, DATA_GROUP_ID, BOT_OWNER_ID

# Set up logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Simple health-check HTTP server for Render
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Telegram bot is running")

def run_web_server():
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    logger.info(f"Starting web server on port {port}")
    server.serve_forever()

# In-memory set of all unique user IDs
unique_users = set()
chart_message_id = None
allowed_users = set()

def now_iso():
    return datetime.utcnow().isoformat() + "Z"

def user_full_name(user: User):
    return f"{user.first_name or ''} {user.last_name or ''}".strip()

async def store_user_data(context: 'telegram.ext.CallbackContext', user_data: dict):
    text = "[USER_DATA]\n" + json.dumps(user_data, ensure_ascii=False)
    try:
        await context.bot.send_message(chat_id=config.DATA_GROUP_ID, text=text)
        logger.info(f"Stored data for user {user_data['user_id']}")
    except TelegramError as e:
        logger.error(f"Failed to send user data: {e}")

async def update_chart(context: 'telegram.ext.CallbackContext'):
    global chart_message_id, unique_users

    count = len(unique_users)
    # Drawing simple bar chart for the count
    fig, ax = plt.subplots(figsize=(6,2))
    ax.bar(1, count, color='skyblue')
    ax.set_ylim(0, max(count+10, 10))
    ax.set_xticks([])
    ax.set_title("Unique Users Tracked")
    # Save to buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close(fig)

    chat_id = config.DATA_GROUP_ID
    bot = context.bot
    try:
        if not chart_message_id:
            msg = await bot.send_photo(chat_id=chat_id, photo=buf, caption=f"Tracked Users: {count}")
            chart_message_id = msg.message_id
        else:
            await bot.edit_message_caption(chat_id=chat_id, message_id=chart_message_id, caption=f"Tracked Users: {count}")
    except TelegramError:
        # If editing caption fails (e.g., message deleted), send new
        try:
            await bot.delete_message(chat_id=chat_id, message_id=chart_message_id)
        except:
            pass
        msg = await bot.send_photo(chat_id=chat_id, photo=buf, caption=f"Tracked Users: {count}")
        chart_message_id = msg.message_id

async def track_new_user(user_id, context):
    global unique_users
    if user_id not in unique_users:
        unique_users.add(user_id)
        await update_chart(context)

# --- Command & Handler functions ---

async def start_command(update: Update, context: 'telegram.ext.CallbackContext'):
    await update.message.reply_text("🤖 Welcome! Tracking group users. Use /help.")

async def allowuser_command(update: Update, context: 'telegram.ext.CallbackContext'):
    if update.effective_user.id != config.BOT_OWNER_ID:
        await update.message.reply_text("Only owner.")
        return
    if len(context.args)!=1 or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /allowuser <id>")
        return
    user_id = int(context.args[0])
    allowed_users.add(user_id)
    await update.message.reply_text(f"Allowed {user_id}")

async def disallowuser_command(update: Update, context: 'telegram.ext.CallbackContext'):
    if update.effective_user.id != config.BOT_OWNER_ID:
        await update.message.reply_text("Only owner.")
        return
    if len(context.args)!=1 or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /disallowuser <id>")
        return
    user_id = int(context.args[0])
    if user_id in allowed_users:
        allowed_users.remove(user_id)
        await update.message.reply_text(f"Disallowed {user_id}")
    else:
        await update.message.reply_text("Not allowed previously.")

async def new_member(update: Update, context: 'telegram.ext.CallbackContext'):
    chat = update.effective_chat
    for user in update.message.new_chat_members:
        data = {
            "user_id": user.id,
            "username": user.username,
            "name": user_full_name(user),
            "event": "joined",
            "group": chat.title,
            "timestamp": now_iso()
        }
        await store_user_data(context, data)
        await track_new_user(user.id, context)

async def member_left(update: Update, context: 'telegram.ext.CallbackContext'):
    user = update.message.left_chat_member
    if user:
        data = {
            "user_id": user.id,
            "username": user.username,
            "name": user_full_name(user),
            "event": "left",
            "group": update.effective_chat.title,
            "timestamp": now_iso()
        }
        await store_user_data(context, data)

async def track_all_users(update: Update, context: 'telegram.ext.CallbackContext'):
    user = update.effective_user
    if not user:
        return
    # Track user count
    await track_new_user(user.id, context)
    # Store message info
    data = {
        "user_id": user.id,
        "username": user.username,
        "name": user_full_name(user),
        "event": "message",
        "group": update.effective_chat.title,
        "timestamp": now_iso()
    }
    await store_user_data(context, data)

# --- Command to show info --- 

async def userinfo_command(update: Update, context: 'telegram.ext.CallbackContext'):
    if not (update.effective_user.id==config.BOT_OWNER_ID or update.effective_user.id in allowed_users):
        await update.message.reply_text("Not authorized.")
        return
    if len(context.args)!=1 or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /userinfo <user_id>")
        return
    uid=int(context.args[0])
    # Fetch last 100 messages from group
    try:
        msgs = await context.bot.get_chat_history(config.DATA_GROUP_ID, limit=100)
    except:
        await update.message.reply_text("Error fetch.")
        return
    user_data_msg = [m for m in msgs if m.text and m.text.startswith("[USER_DATA]")]
    user_data_list = []
    for m in user_data_msg:
        try:
            data = json.loads(m.text.split("\n",1)[1])
            if data.get("user_id")==uid:
                user_data_list.append(data)
        except:
            continue
    if not user_data_list:
        await update.message.reply_text("No data.")
        return
    latest = user_data_list[-1]
    groups = {d.get("group") for d in user_data_list}
    groups.discard(None)
    await update.message.reply_text(
        f"ID:{uid}\nUsername:{latest.get('username')}\nName:{latest.get('name')}\nGroups:{len(groups)}"
    )

# --- Main ---
def main():
    threading.Thread(target=run_web_server, daemon=True).start()

    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("allowuser", allowuser_command))
    app.add_handler(CommandHandler("disallowuser", disallowuser_command))
    app.add_handler(CommandHandler("userinfo", userinfo_command))
    app.add_handler(CommandHandler("scannedcount", lambda u,c: c.bot.get_chat_history_async_bug_check())) # your fix
    app.add_handler(CommandHandler("help", lambda u,c: c.bot.send_message(chat_id=u.effective_chat.id, text="Help")))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, member_left))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), track_all_users))

    app.run_polling()

# Call the main
if __name__=="__main__":
    main()
