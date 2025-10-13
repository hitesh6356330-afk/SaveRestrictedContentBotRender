import logging
import asyncio
import re
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
import instaloader
import config

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

L = instaloader.Instaloader()

instagram_session = {
    "logged_in": False,
    "username": None,
    "password": None,
}

def user_is_owner(user_id):
    return user_id == config.BOT_OWNER_ID

def extract_instagram_username(text):
    pattern = r"(?:https?://)?(?:www\.)?instagram\.com/([a-zA-Z0-9._]+)/?"
    match = re.match(pattern, text)
    return match.group(1) if match else text.strip('@')


async def login_instagram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_is_owner(update.effective_user.id):
        await update.message.reply_text("Unauthorized: Only bot owner can use this command.")
        return
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /login <instagram_username> <instagram_password>")
        return
    username, password = context.args
    try:
        L.login(username, password)
        instagram_session.update({
            "logged_in": True,
            "username": username,
            "password": password,
        })
        await update.message.reply_text(f"Logged in to Instagram as @{username}")
        logger.info(f"Instagram logged in as {username}")
    except Exception as e:
        logger.error(f"Instagram login failed: {e}")
        await update.message.reply_text(f"Login failed: {e}")


async def logout_instagram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_is_owner(update.effective_user.id):
        await update.message.reply_text("Unauthorized: Only bot owner can use this command.")
        return
    instagram_session.update({
        "logged_in": False,
        "username": None,
        "password": None,
    })
    await update.message.reply_text("Logged out from Instagram.")


async def fetch_posts(username, bot, chat_id, max_posts=10):
    try:
        profile = instaloader.Profile.from_username(L.context, username)
    except Exception as e:
        logger.error(f"Failed to load profile @{username}: {e}")
        await bot.send_message(chat_id=chat_id, text=f"Failed to load Instagram profile @{username}")
        return
    
    sent = 0
    for post in profile.get_posts():
        if sent >= max_posts:
            break
        caption = post.caption or ""
        try:
            if post.is_video:
                await bot.send_video(chat_id=chat_id, video=post.video_url, caption=caption[:1000])
            else:
                await bot.send_photo(chat_id=chat_id, photo=post.url, caption=caption[:1000])
            sent += 1
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Failed to send Instagram post {post.shortcode}: {e}")

    if sent == 0:
        await bot.send_message(chat_id=chat_id, text=f"No posts found for @{username}")


async def fetch_stories(username, bot, chat_id):
    if not instagram_session["logged_in"]:
        await bot.send_message(chat_id=chat_id, text="Stories require logged-in Instagram session. Please /login first.")
        return

    try:
        profile = instaloader.Profile.from_username(L.context, username)
    except Exception as e:
        logger.error(f"Failed to load profile for stories @{username}: {e}")
        await bot.send_message(chat_id=chat_id, text=f"Failed to load profile for stories @{username}")
        return

    sent = 0
    try:
        for story in L.get_stories(userids=[profile.userid]):
            for item in story.get_items():
                caption = f"Story by @{username}"
                if item.is_video:
                    await bot.send_video(chat_id=chat_id, video=item.video_url, caption=caption)
                else:
                    await bot.send_photo(chat_id=chat_id, photo=item.url, caption=caption)
                sent += 1
                await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"Failed fetching stories for @{username}: {e}")

    if sent == 0:
        await bot.send_message(chat_id=chat_id, text=f"No active stories for @{username}")


async def fetch_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_is_owner(update.effective_user.id):
        await update.message.reply_text("Unauthorized: Only bot owner can use this command.")
        return
    if len(context.args) == 0:
        await update.message.reply_text("Usage: /fetch_user <instagram_username_or_link>")
        return
    input_text = context.args[0]
    username = extract_instagram_username(input_text)

    chat_id = config.DATA_GROUP_ID  # dump group ID from config

    await update.message.reply_text(f"Fetching posts and stories for @{username}...")

    await fetch_posts(username, context.bot, chat_id, max_posts=10)
    await fetch_stories(username, context.bot, chat_id)

    await update.message.reply_text(f"Completed fetching content for @{username}.")


async def fetch_and_send_instagram_post_by_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    pattern = r"(?:https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/)?([A-Za-z0-9_-]+)/?"
    match = re.search(pattern, text)
    if not match:
        return
    shortcode = match.group(1)
    chat_id = config.DATA_GROUP_ID

    await update.message.reply_text(f"Fetching Instagram media for shortcode: {shortcode}")

    try:
        post = instaloader.Post.from_shortcode(L.context, shortcode)
        caption = post.caption or ""

        if post.is_video:
            await context.bot.send_video(chat_id=chat_id, video=post.video_url, caption=caption[:1000])
        else:
            await context.bot.send_photo(chat_id=chat_id, photo=post.url, caption=caption[:1000])

        await update.message.reply_text("Media sent to dump group.")
        logger.info(f"Sent Instagram media for shortcode: {shortcode}")
    except Exception as e:
        logger.error(f"Failed to fetch/send Instagram media for shortcode {shortcode}: {e}")
        await update.message.reply_text(f"Failed to fetch Instagram media: {e}")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome! Commands:\n"
        "/login <username> <password> - Login to Instagram\n"
        "/fetch_user <username_or_link> - Fetch posts & stories of any Instagram user to dump group\n"
        "/logout - Logout from Instagram session\n"
        "Send Instagram post/reel links in chat to fetch media directly."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\n"
        "/login <username> <password>\n"
        "/fetch_user <username_or_link>\n"
        "/logout\n"
        "Send Instagram post/reel URL or shortcode in chat to fetch it directly.\n"
        "Only bot owner can run commands."
    )


def main():
    application = ApplicationBuilder().token(config.BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("login", login_instagram))
    application.add_handler(CommandHandler("logout", logout_instagram))
    application.add_handler(CommandHandler("fetch_user", fetch_user))

    # Handler to detect Instagram post/reel links or shortcodes in any chat message
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), fetch_and_send_instagram_post_by_link))

    application.run_polling()


if __name__ == "__main__":
    main()
