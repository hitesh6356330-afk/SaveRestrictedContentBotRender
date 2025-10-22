import os
import asyncio
import aiohttp
from pyrogram import Client, filters

EXTERNAL_PING_URL = "https://scanrobot-kul1.onrender.com"

async def ping_render_url():
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(EXTERNAL_PING_URL) as response:
                    print(f"Pinged {EXTERNAL_PING_URL} with status {response.status}")
        except Exception as e:
            print(f"Failed to ping {EXTERNAL_PING_URL}: {e}")
        await asyncio.sleep(4 * 60)  # ping every 4 minutes

async def main():
    API_ID = int(os.getenv("21747552"))
    API_HASH = os.getenv("b1e6c2c3a183f0fa7219db450650ee8a")
    BOT_TOKEN = os.getenv("8268550979:AAFBPEKkaNCEgCBza3Qcmg4K50FZj92CopM")

    app = Client(
        "SaveRestrictedContentBot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN
    )

    @app.on_message(filters.command("start") & filters.private)
    async def start(client, message):
        await message.reply_text("Hello! SaveRestrictedContentBot is running on Render.")

    @app.on_message(filters.command("batch"))
    async def batch_save(client, message):
        await message.reply_text("Batch saving initiated...")

    await asyncio.gather(app.start(), ping_render_url())
    print("Bot started. Press Ctrl+C to stop.")
    await app.idle()

if __name__ == "__main__":
    asyncio.run(main())
