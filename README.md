# SaveRestrictedContentBot

A Telegram bot to save restricted content from channels, with custom thumbnail support.

## Setup & Deployment on Render

1. Add your environment variables in the Render dashboard (`API_ID`, `API_HASH`, `BOT_TOKEN`).
2. Deploy this repository using Render.
3. The bot will start and listen for commands on Telegram.
4. It keeps Render service alive by pinging the external URL: https://scanrobot-kul1.onrender.com

## Commands

- `/start` - Verify the bot is running.
- `/batch` - Initiates batch saving.
