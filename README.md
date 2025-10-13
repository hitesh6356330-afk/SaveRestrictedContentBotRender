# Scanrobot

# Telegram Webhook Bot for Render Deployment

This is a sample Python Telegram bot built using FastAPI and python-telegram-bot library with webhook support, ready for deployment on Render.

## Features
- Uses webhook instead of polling for better production deployment
- Stores user info in a dedicated Telegram group acting as a database
- Easily extensible to crawl users and retrieve data

## Setup

1. Create a Telegram bot via @BotFather and get the BOT_TOKEN.
2. Create a Telegram group where the bot can store user info and get its group chat ID.
3. Set environment variables:

