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
import matplotlib
matplotlib.use('Agg')  # Headless backend for servers
import matplotlib.pyplot as plt
import os
import instaloader
import asyncio
import re

import config  # Your config.py with BOT_TOKEN, DATA_GROUP_ID, BOT_OWNER_ID

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

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


unique_users = set()
chart_message_id = None
allowed_users = set()

L = instaloader.Instaloader()

tracked_instagram_users = set()
user_last_post_dates = {}

def now_iso():
    return datetime.utcnow().isoformat() + "Z"

def user_full_name(user: User):
    return f"{user.first_name or ''} {user.last_name or ''}".strip()

def extract_instagram_username(url):
    pattern = r"(?:https?://)?(?:www\.)?instagram\.com/([a-zA-Z0-9._]+)/?"
    match = re.match(pattern, url)
    return match.group(1) if match else None

async def store_user_data(context: ContextTypes.DEFAULT_TYPE, user_data: dict):
    text = "[USER_DATA]\n" + json.dumps(user_data, ensure_ascii=False)
    logger.info(f"Attempting to send user data for user {user_data.get('user_id')}")
    try:
        await context.bot.send_message(chat_id=config.DATA_GROUP_ID, text=text)
        logger.info(f"Successfully sent user data for user {user_data.get('user_id')}")
    except TelegramError as e:
        logger.error(f"Failed to send user data: {e}")

def user_is_allowed(user_id):
    return user_id == config.BOT_OWNER_ID or user_id in allowed_users

async def update_chart(context: ContextTypes.DEFAULT_TYPE):
    global chart_message_id, unique_users

    count = len(unique_users)
    logger.info(f"Generating chart for {count} unique users...")
    fig, ax = plt.subplots(figsize=(6, 2))
    ax.bar(1, count, color='skyblue')
    ax.set_ylim(0, max(count + 10, 10))
    ax.set_xticks([])
    ax.set_title("Total Unique Users Tracked")
    ax.set_ylabel("Count")

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close(fig)
    logger.info(f"Chart image buffer size: {buf.getbuffer().nbytes} bytes")

    chat_id = config.DATA_GROUP_ID
    bot = context.bot

    try:
        if chart_message_id is None:
            msg = await bot.send_photo(chat_id=chat_id, photo=buf, caption=f"Tracked Users: {count}")
            chart_message_id = msg.message_id
            logger.info(f"Created new chart message id: {chart_message_id}")
        else:
            await bot.edit_message_caption(chat_id=chat_id, message_id=chart_message_id, caption=f"Tracked Users: {count}")
            logger.info(f"Updated chart message caption to count {count}")
    except TelegramError as e:
        logger.error(f"Failed to update chart message: {e}")
        try:
            await bot.delete_message(chat_id=chat_id, message_id=chart_message_id)
        except Exception:
            logger.warning("Could not delete old chart message")
        msg = await bot.send_photo(chat_id=chat_id, photo=buf, caption=f"Tracked Users: {count}")
        chart_message_id = msg.message_id
        logger.info(f"Recreated chart message after error, new id: {chart_message_id}")

async def track_new_user(user_id, context):
    global unique_users
    if user_id not in unique_users:
        unique_users.add(user_id)
        await update_chart(context)

async def unwrap_async_iterator(sync_iter):
    for item in sync_iter:
        yield item

async def fetch_and_send_instagram_posts(username, context):
    try:
        profile = instaloader.Profile.from_username(L.context, username)
    except Exception as exc:
        logger.error(f"Failed to fetch Instagram profile @{username}: {exc}")
        return

    last_date = user_last_post_dates.get(username)
    sent_new = False

    async for post in unwrap_async_iterator(profile.get_posts()):
        post_date = post.date.replace(tzinfo=None)
        if last_date is not None and post_date <= last_date:
            break

        caption = post.caption or ""
        post_url = post.url

        try:
            if post.is_video:
                await context.bot.send_video(
                    chat_id=config.DATA_GROUP_ID,
                    video=post_url,
                    caption=f"Instagram Video @{username}:\n{caption[:1000]}"
                )
            else:
                await context.bot.send_photo(
                    chat_id=config.DATA_GROUP_ID,
                    photo=post_url,
                    caption=f"Instagram @{username}:\n{caption[:1000]}"
                )
            logger.info(f"Sent Instagram post {post.shortcode} from @{username}")
            sent_new = True
        except Exception as e:
            logger.error(f"Failed to send Instagram post: {e}")

        if last_date is None or post_date > last_date:
            user_last_post_dates[username] = post_date

    if not sent_new:
        logger.info(f"No new posts found for @{username}")

async def instagram_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /instagram_add <instagram_username_or_profile_link>")
        return
    input_text = context.args[0].strip()
    username = extract_instagram_username(input_text)
    if username is None:
        username = input_text.lstrip('@')
    if username in tracked_instagram_users:
        await update.message.reply_text(f"Instagram user @{username} is already being tracked.")
        return
    tracked_instagram_users.add(username)
    await update.message.reply_text(f"Added Instagram user @{username} for tracking.")
    await fetch_and_send_instagram_posts(username, context)

async def handle_instagram_video_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text
    ig_video_pattern = r"(https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[A-Za-z0-9_\-]+)/?"
    match = re.search(ig_video_pattern, message_text)
    if not match:
        return
    url = match.group(0)
    await update.message.reply_text(f"Processing Instagram video URL...")

    try:
        shortcode = url.strip('/').split('/')[-1]
        post = instaloader.Post.from_shortcode(L.context, shortcode)
        video_url = post.video_url
        caption = post.caption or ""
        await context.bot.send_video(chat_id=config.DATA_GROUP_ID, video=video_url, caption=f"Instagram Video:\n{caption[:1000]}")
        await update.message.reply_text("Video sent to database group.")
    except Exception as e:
        logger.error(f"Failed to fetch/send Instagram video: {e}")
        await update.message.reply_text("Failed to process Instagram video link.")

# Your previous handlers follow here, added exactly as you had them before:

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Welcome! Use /help to see commands.")

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Test command received!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("""Available commands:
/start - Start the bot
/help - Show this help message
/instagram_add <username_or_link> - Track Instagram posts and reels
Other commands as before.""") 

async def allowuser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.BOT_OWNER_ID:
        await update.message.reply_text("Only the bot owner can allow users.")
        return
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /allowuser <user_id>")
        return
    user_id = int(context.args[0])
    allowed_users.add(user_id)
    await update.message.reply_text(f"User {user_id} has been allowed.")

async def disallowuser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.BOT_OWNER_ID:
        await update.message.reply_text("Only the bot owner can disallow users.")
        return
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /disallowuser <user_id>")
        return
    user_id = int(context.args[0])
    if user_id in allowed_users:
        allowed_users.remove(user_id)
        await update.message.reply_text(f"User {user_id} has been disallowed.")
    else:
        await update.message.reply_text(f"User {user_id} was not allowed before.")

async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    for user in update.message.new_chat_members:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "name": user_full_name(user),
            "event": "joined",
            "group": chat.title,
            "timestamp": now_iso()
        }
        await store_user_data(context, user_data)
        await track_new_user(user.id, context)

async def member_left(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.message.left_chat_member
    if user:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "name": user_full_name(user),
            "event": "left",
            "group": chat.title,
            "timestamp": now_iso()
        }
        await store_user_data(context, user_data)

async def track_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_title = update.effective_chat.title if update.effective_chat else None
    if user:
        user_data = {
            "user_id": user.id,
            "username": user.username,
            "name": user_full_name(user),
            "event": "message",
            "group": chat_title,
            "timestamp": now_iso()
        }
        await store_user_data(context, user_data)
        await track_new_user(user.id, context)

async def userinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_is_allowed(update.effective_user.id):
        await update.message.reply_text("You are not authorized to use this command.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("Usage: /userinfo <user_id>")
        return

    user_id_str = context.args[0]
    if not user_id_str.isdigit():
        await update.message.reply_text("User ID must be a number.")
        return
    user_id = int(user_id_str)

    try:
        messages = await context.bot.get_chat_history(config.DATA_GROUP_ID, limit=1000)
    except Exception as e:
        logger.error(f"Error fetching chat history: {e}")
        await update.message.reply_text("Failed to fetch user data from database group.")
        return

    user_messages = []
    for message in messages:
        if message.text and message.text.startswith("[USER_DATA]"):
            try:
                data = json.loads(message.text.split("\n", 1)[1])
                if data.get("user_id") == user_id:
                    user_messages.append(data)
            except Exception:
                continue

    if not user_messages:
        await update.message.reply_text("No data found for this user.")
        return

    latest = user_messages[-1]
    username = latest.get("username", "None")
    name = latest.get("name", "None")
    groups = {m.get("group") for m in user_messages if m.get("group")}
    groups.discard(None)
    group_count = len(groups)

    reply = (
        f"Human found!\n"
        f"Telegram ID: {user_id}\n"
        f"Username: {username}\n"
        f"Name: {name}\n"
        f"Number of groups found: {group_count}\n"
        f"Groups: {', '.join(groups) if groups else 'None'}"
    )
    await update.message.reply_text(reply)

async def scannedcount_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_is_allowed(update.effective_user.id):
        await update.message.reply_text("You are not authorized to use this command.")
        return

    try:
        messages = await context.bot.get_chat_history(config.DATA_GROUP_ID, limit=1000)
    except Exception as e:
        logger.error(f"Error fetching chat history: {e}")
        await update.message.reply_text("Failed to count scanned users.")
        return

    count = sum(1 for m in messages if m.text and m.text.startswith("[USER_DATA]"))
    await update.message.reply_text(f"Currently scanned and tracked user records: {count}")

async def pingall_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_is_allowed(update.effective_user.id):
        await update.message.reply_text("You are not authorized to use this command.")
        return
    if len(unique_users) == 0:
        await update.message.reply_text("No users tracked yet.")
        return
    await update.message.reply_text(
        "👋 Hello friends! Don’t forget to send /stayactive to keep enjoying this group’s benefits! 🚀"
    )

async def stayactive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"Thanks for staying active, {user.first_name}! Keep enjoying the group 😀"
    )

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("This command can only be used in groups.")
        return
    try:
        total_members = await context.bot.get_chat_member_count(chat.id)
        await context.bot.send_message(chat.id, f"Starting scan of {total_members} members in this group...")
        admins = await context.bot.get_chat_administrators(chat.id)
        count = 0
        for admin in admins:
            user = admin.user
            user_data = {
                "user_id": user.id,
                "username": user.username,
                "name": user_full_name(user),
                "event": "scanned",
                "group": chat.title or "",
                "timestamp": now_iso()
            }
            await store_user_data(context, user_data)
            await track_new_user(user.id, context)
            count += 1
            if count % 10 == 0:
                await context.bot.send_message(chat.id, f"Scanned {count} admins so far...")
        await context.bot.send_message(chat.id, f"Scan complete! Tracked {count} admins/members (prototype).")
    except Exception as e:
        logger.error(f"Error in scanning: {e}")
        await context.bot.send_message(chat.id, f"Error during scan: {e}")

# Debug echo handler
async def debug_echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text:
        await update.message.reply_text(f"Echo: {update.message.text}")

def main():
    threading.Thread(target=run_fake_webserver, daemon=True).start()

    application = ApplicationBuilder().token(config.BOT_TOKEN).concurrent_updates(True).build()

    # Register command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(CommandHandler("instagram_add", instagram_add_command))
    application.add_handler(CommandHandler("userinfo", userinfo_command))
    application.add_handler(CommandHandler("scannedcount", scannedcount_command))
    application.add_handler(CommandHandler("pingall", pingall_command))
    application.add_handler(CommandHandler("stayactive", stayactive_command))
    application.add_handler(CommandHandler("allowuser", allowuser_command))
    application.add_handler(CommandHandler("disallowuser", disallowuser_command))

    # Register message handlers
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, member_left))
    # Instagram video/reel/igtv links
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_instagram_video_link))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track_all_users))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, debug_echo))

    # Start Instagram monitoring loop
    loop = asyncio.get_event_loop()
    loop.create_task(instagram_monitor_loop(application))

    application.run_polling()

async def instagram_monitor_loop(application):
    while True:
        for username in list(tracked_instagram_users):
            try:
                await fetch_and_send_instagram_posts(username, application)
            except Exception as e:
                logger.error(f"Error monitoring Instagram user @{username}: {e}")
        await asyncio.sleep(1800)

if __name__ == "__main__":
    main()
