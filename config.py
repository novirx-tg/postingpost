import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN or BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
    # Let's not raise an exception immediately during import, so that the code is testable,
    # but we'll print a warning or allow fallback.
    # We will check it when starting the bot in main.py.
    pass

DATABASE_PATH = "posting_bot.db"
