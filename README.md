# Scanrobot
# Telegram User Tracker Bot

This bot tracks user join/leave events, and profile changes (username, name) in Telegram groups it is added to.  
It stores all data as JSON messages in a dedicated Telegram group used as a simple database.  
It allows querying user info using the `/userinfo <user_id>` command.

## Features

- Logs when users join or leave groups.
- Tracks username and name changes upon any message by a user.
- Stores user event data as JSON inside a designated Telegram group.
- Fetch user info and number of groups found with a simple command.
- Completely free to use; no credit or paywall system.

## Setup Instructions

1. Create a Telegram bot with [@BotFather](https://t.me/BotFather) and get the API token.
2. Create a Telegram group for storing user data, add your bot there and make it an admin.
3. Get the group ID (negative number), can be found via https://t.me/getidsbot or via the Telegram API.
4. Edit `config.py` to add your bot token and group ID.
5. Install dependencies:
