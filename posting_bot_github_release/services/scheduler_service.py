import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from database import Database
from services.post_service import send_post

logger = logging.getLogger(__name__)

class SchedulerService:
    def __init__(self, bot: Bot, db: Database):
        self.bot = bot
        self.db = db
        self.scheduler = AsyncIOScheduler()

    async def start(self):
        self.scheduler.start()
        logger.info("Scheduler started.")
        await self._load_pending_jobs()

    async def _load_pending_jobs(self):
        # Fetch all scheduled posts
        scheduled_posts = self.db.get_posts_by_status('scheduled')
        logger.info(f"Loading scheduled posts. Found: {len(scheduled_posts)}")
        now = datetime.now()
        for post in scheduled_posts:
            post_id = post['post_id']
            sched_time_str = post['scheduled_at']
            if not sched_time_str:
                continue
            try:
                # Parse YYYY-MM-DD HH:MM:SS or ISO format
                try:
                    sched_time = datetime.strptime(sched_time_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    sched_time = datetime.fromisoformat(sched_time_str)
            except ValueError as e:
                logger.error(f"Cannot parse scheduled time: {sched_time_str} for post {post_id}: {e}")
                continue
            
            if sched_time <= now:
                # If time passed while bot was offline, post now!
                logger.info(f"Scheduled time for post {post_id} already passed ({sched_time_str}). Posting now.")
                await self._run_job(post_id, post['channel_id'])
            else:
                self.add_job(post_id, post['channel_id'], sched_time)

    def add_job(self, post_id: int, channel_id: int, run_date: datetime):
        job_id = f"post_{post_id}"
        # If job already exists, remove it first
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            
        self.scheduler.add_job(
            self._run_job,
            trigger='date',
            run_date=run_date,
            args=[post_id, channel_id],
            id=job_id
        )
        logger.info(f"Scheduled job {job_id} for {run_date}")

    def remove_job(self, post_id: int):
        job_id = f"post_{post_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            logger.info(f"Removed job {job_id}")

    async def _run_job(self, post_id: int, channel_id: int):
        logger.info(f"Executing scheduled post {post_id}")
        await send_post(self.bot, self.db, post_id, channel_id)
