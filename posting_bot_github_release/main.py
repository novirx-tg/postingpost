import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN, DATABASE_PATH
from database import Database
from services.scheduler_service import SchedulerService

# Import handlers
from handlers.start import router as start_router
from handlers.channels import router as channels_router
from handlers.post_creator import router as post_creator_router
from handlers.scheduler import router as scheduler_router
from handlers.history import router as history_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

async def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.error("BOT_TOKEN is not set in the .env file. Please edit .env and insert your bot token.")
        print("\n" + "="*80)
        print("ERROR: BOT_TOKEN is not configured!")
        print("Please open the .env file in the bot folder and replace YOUR_TELEGRAM_BOT_TOKEN with your actual token.")
        print("="*80 + "\n")
        return

    # Initialize database
    db = Database(DATABASE_PATH)
    logger.info("Database initialized successfully.")

    # Initialize bot and dispatcher
    bot = Bot(
        token=BOT_TOKEN, 
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # Initialize scheduler service
    scheduler_service = SchedulerService(bot, db)

    # Context injection (shares instances with all handlers)
    dp.workflow_data.update(
        db=db,
        scheduler_service=scheduler_service
    )

    # Register routers (order is important for FSM and command filtering)
    dp.include_router(start_router)
    dp.include_router(channels_router)
    dp.include_router(post_creator_router)
    dp.include_router(scheduler_router)
    dp.include_router(history_router)

    logger.info("Handlers and routers registered.")

    # Start the APScheduler before polling starts
    await scheduler_service.start()

    logger.info("Starting bot polling...")
    try:
        # Skip accumulated updates on startup
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("Bot session closed.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
