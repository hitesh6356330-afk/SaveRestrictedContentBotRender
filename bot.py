import logging
import asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
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
}


def user_is_owner(user_id):
    return user_id == config.BOT_OWNER_ID


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
        instagram_session["logged_in"] = True
        instagram_session["username"] = username
        await update.message.reply_text(f"Logged in to Instagram as @{username}")
        logger.info(f"Instagram logged in as {username}")
    except Exception as e:
        logger.error(f"Instagram login failed: {e}")
        await update.message.reply_text(f"Login failed: {e}")


async def fetch_my_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_is_owner(update.effective_user.id):
        await update.message.reply_text("Unauthorized: Only bot owner can use this command.")
        return

    if not instagram_session["logged_in"]:
        await update.message.reply_text("You need to /login first.")
        return

    count = 3  # default
    if context.args and context.args[0].isdigit():
        count = int(context.args[0])

    try:
        profile = instaloader.Profile.from_username(L.context, instagram_session["username"])
        posts = list(profile.get_posts())
    except Exception as e:
        logger.error(f"Failed to get Instagram profile/posts: {e}")
        await update.message.reply_text(f"Failed to get Instagram posts: {e}")
        return

    sent = 0
    for post in posts[:count]:
        caption = post.caption or ""
        try:
            if post.is_video:
                await context.bot.send_video(
                    chat_id=update.effective_chat.id,
                    video=post.video_url,
                    caption=caption[:1000],
                )
            else:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=post.url,
                    caption=caption[:1000],
                )
            sent += 1
            await asyncio.sleep(1)  # rate limit friendly
        except Exception as e:
            logger.error(f"Failed to send Instagram post: {e}")

    if sent == 0:
        await update.message.reply_text("No posts sent.")
    else:
        await update.message.reply_text(f"Sent {sent} post(s).")


async def logout_instagram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_is_owner(update.effective_user.id):
        await update.message.reply_text("Unauthorized: Only bot owner can use this command.")
        return

    instagram_session["logged_in"] = False
    instagram_session["username"] = None
    await update.message.reply_text("Logged out from Instagram.")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome! Use /login <username> <password> to log in to Instagram.\n"
        "Use /fetch_my_posts [count] to fetch your recent posts.\n"
        "Use /logout to log out."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\n"
        "/start - Welcome message\n"
        "/login <username> <password> - Log in to Instagram\n"
        "/fetch_my_posts [count] - Fetch your latest Instagram posts\n"
        "/logout - Log out from Instagram"
    )


def main():
    application = ApplicationBuilder().token(config.BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("login", login_instagram))
    application.add_handler(CommandHandler("fetch_my_posts", fetch_my_posts))
    application.add_handler(CommandHandler("logout", logout_instagram))

    application.run_polling()


if __name__ == "__main__":
    main()
