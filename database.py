import aiosqlite
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

class Database:
    ALLOWED_POST_COLUMNS = {
        'user_id', 'channel_id', 'content_type', 'text', 'media_file_id', 
        'buttons_json', 'reactions_json', 'message_effect_id', 'parse_mode', 
        'status', 'scheduled_at', 'table_matrix_json', 'from_chat_id', 
        'source_message_id', 'show_caption_above_media', 'has_spoiler', 
        'link_preview_options_json', 'star_count', 'poll_data_json'
    }

    def __init__(self, db_path: str = "posting_bot.db"):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> aiosqlite.Connection:
        """
        Creates or returns the active persistent asynchronous SQLite connection.
        Enables WAL mode, foreign keys cascade, and busy timeout.
        """
        if self._conn is None:
            self._conn = await aiosqlite.connect(self.db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA foreign_keys = ON;")
            await self._conn.execute("PRAGMA journal_mode = WAL;")
            await self._conn.execute("PRAGMA synchronous = NORMAL;")
            await self._conn.execute("PRAGMA busy_timeout = 5000;")
            await self._conn.commit()
            logger.info("Persistent aiosqlite connection established (WAL mode, foreign keys ON).")
        return self._conn

    async def get_connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            return await self.connect()
        return self._conn

    async def close(self):
        """Safely closes the persistent database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            logger.info("aiosqlite connection closed.")

    async def init_db(self):
        """
        Runs versioned database migrations in sequence to ensure schema integrity.
        """
        conn = await self.get_connection()

        # Create migrations tracking table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.commit()

        # Fetch applied migrations
        async with conn.execute("SELECT version FROM schema_migrations") as cursor:
            applied = {row[0] for row in await cursor.fetchall()}

        # Migration 1: Base schema
        if 1 not in applied:
            logger.info("Applying database migration 1: base tables...")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS channels (
                    channel_id INTEGER PRIMARY KEY,
                    title TEXT,
                    username TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_channels (
                    user_id INTEGER,
                    channel_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, channel_id),
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS posts (
                    post_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    channel_id INTEGER,
                    content_type TEXT,
                    text TEXT,
                    media_file_id TEXT,
                    buttons_json TEXT,
                    reactions_json TEXT,
                    message_effect_id TEXT,
                    parse_mode TEXT DEFAULT 'HTML',
                    status TEXT DEFAULT 'draft',
                    scheduled_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS sent_posts (
                    channel_id INTEGER,
                    message_id INTEGER,
                    post_id INTEGER,
                    PRIMARY KEY (channel_id, message_id),
                    FOREIGN KEY (post_id) REFERENCES posts(post_id) ON DELETE CASCADE
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS votes (
                    post_id INTEGER,
                    user_id INTEGER,
                    reaction TEXT,
                    PRIMARY KEY (post_id, user_id),
                    FOREIGN KEY (post_id) REFERENCES posts(post_id) ON DELETE CASCADE
                )
            """)
            await conn.execute("INSERT INTO schema_migrations (version) VALUES (1)")
            await conn.commit()
            logger.info("Migration 1 applied successfully.")

        # Migration 2: Rich tables and forwarded message metadata
        if 2 not in applied:
            logger.info("Applying database migration 2: rich blocks & source message metadata...")
            # Check existing columns in posts
            async with conn.execute("PRAGMA table_info(posts)") as cursor:
                columns = {row[1] for row in await cursor.fetchall()}

            for col_name, col_type in [
                ("message_effect_id", "TEXT"),
                ("parse_mode", "TEXT DEFAULT 'HTML'"),
                ("table_matrix_json", "TEXT"),
                ("from_chat_id", "BIGINT"),
                ("source_message_id", "BIGINT")
            ]:
                if col_name not in columns:
                    await conn.execute(f"ALTER TABLE posts ADD COLUMN {col_name} {col_type}")

            await conn.execute("INSERT INTO schema_migrations (version) VALUES (2)")
            await conn.commit()
            logger.info("Migration 2 applied successfully.")

        # Migration 3: Media groups (albums) table and modern Telegram Bot API features
        if 3 not in applied:
            logger.info("Applying database migration 3: post_media albums & Bot API features...")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS post_media (
                    media_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id INTEGER NOT NULL,
                    media_type TEXT NOT NULL, -- 'photo', 'video', 'document', 'audio'
                    file_id TEXT NOT NULL,
                    position INTEGER DEFAULT 0,
                    has_spoiler BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (post_id) REFERENCES posts(post_id) ON DELETE CASCADE
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_post_media_post_id ON post_media(post_id)")

            # Check existing columns in posts
            async with conn.execute("PRAGMA table_info(posts)") as cursor:
                columns = {row[1] for row in await cursor.fetchall()}

            for col_name, col_type in [
                ("show_caption_above_media", "BOOLEAN DEFAULT 0"),
                ("has_spoiler", "BOOLEAN DEFAULT 0"),
                ("link_preview_options_json", "TEXT")
            ]:
                if col_name not in columns:
                    await conn.execute(f"ALTER TABLE posts ADD COLUMN {col_name} {col_type}")

            await conn.execute("INSERT INTO schema_migrations (version) VALUES (3)")
            await conn.commit()
            logger.info("Migration 3 applied successfully.")

        # Migration 4: Paid media stars and poll posts (Bot API 8.x - 10.x)
        if 4 not in applied:
            logger.info("Applying database migration 4: star_count & poll_data_json...")
            async with conn.execute("PRAGMA table_info(posts)") as cursor:
                columns = {row[1] for row in await cursor.fetchall()}

            for col_name, col_type in [
                ("star_count", "INTEGER DEFAULT 0"),
                ("poll_data_json", "TEXT")
            ]:
                if col_name not in columns:
                    await conn.execute(f"ALTER TABLE posts ADD COLUMN {col_name} {col_type}")

            await conn.execute("INSERT INTO schema_migrations (version) VALUES (4)")
            await conn.commit()
            logger.info("Migration 4 applied successfully.")

    # ------------------- Users -------------------
    async def add_user(self, user_id: int, username: str, first_name: str):
        conn = await self.get_connection()
        await conn.execute("""
            INSERT INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name
        """, (user_id, username, first_name))
        await conn.commit()

    # ------------------- Channels -------------------
    async def add_channel(self, channel_id: int, title: str, username: str, user_id: int):
        conn = await self.get_connection()
        # Add to channels if not exists
        await conn.execute("""
            INSERT INTO channels (channel_id, title, username)
            VALUES (?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                title = excluded.title,
                username = excluded.username
        """, (channel_id, title, username))
        
        # Link to user
        await conn.execute("""
            INSERT OR IGNORE INTO user_channels (user_id, channel_id)
            VALUES (?, ?)
        """, (user_id, channel_id))
        await conn.commit()

    async def remove_channel(self, channel_id: int, user_id: int):
        conn = await self.get_connection()
        await conn.execute("""
            DELETE FROM user_channels
            WHERE user_id = ? AND channel_id = ?
        """, (user_id, channel_id))
        await conn.commit()

    async def get_channels_by_user(self, user_id: int) -> List[Dict[str, Any]]:
        conn = await self.get_connection()
        async with conn.execute("""
            SELECT c.channel_id, c.title, c.username 
            FROM channels c
            JOIN user_channels uc ON c.channel_id = uc.channel_id
            WHERE uc.user_id = ?
            ORDER BY c.created_at DESC
        """, (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ------------------- Posts -------------------
    async def create_post(self, user_id: int, channel_id: int, content_type: str = 'text', 
                          text: Optional[str] = None, media_file_id: Optional[str] = None, 
                          buttons_json: Optional[str] = None, reactions_json: Optional[str] = None, 
                          status: str = 'draft', scheduled_at: Optional[str] = None,
                          message_effect_id: Optional[str] = None, parse_mode: str = 'HTML',
                          table_matrix_json: Optional[str] = None, from_chat_id: Optional[int] = None,
                          source_message_id: Optional[int] = None,
                          show_caption_above_media: bool = False,
                          has_spoiler: bool = False,
                          link_preview_options_json: Optional[str] = None,
                          star_count: int = 0,
                          poll_data_json: Optional[str] = None) -> int:
        conn = await self.get_connection()
        async with conn.execute("""
            INSERT INTO posts (
                user_id, channel_id, content_type, text, media_file_id, 
                buttons_json, reactions_json, message_effect_id, parse_mode, 
                status, scheduled_at, table_matrix_json, from_chat_id, source_message_id,
                show_caption_above_media, has_spoiler, link_preview_options_json,
                star_count, poll_data_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, channel_id, content_type, text, media_file_id, 
            buttons_json, reactions_json, message_effect_id, parse_mode, 
            status, scheduled_at, table_matrix_json, from_chat_id, source_message_id,
            1 if show_caption_above_media else 0,
            1 if has_spoiler else 0,
            link_preview_options_json,
            star_count,
            poll_data_json
        )) as cursor:
            post_id = cursor.lastrowid
            await conn.commit()
            return post_id

    async def update_post(self, post_id: int, **kwargs):
        if not kwargs:
            return
        fields = []
        values = []
        for key, val in kwargs.items():
            if key not in self.ALLOWED_POST_COLUMNS:
                raise ValueError(f"Недопустимое имя столбца: {key}")
            # Convert booleans to int for sqlite
            if isinstance(val, bool):
                val = 1 if val else 0
            fields.append(f"{key} = ?")
            values.append(val)
        values.append(post_id)
        
        conn = await self.get_connection()
        query = f"UPDATE posts SET {', '.join(fields)} WHERE post_id = ?"
        await conn.execute(query, tuple(values))
        await conn.commit()

    async def get_post(self, post_id: int) -> Optional[Dict[str, Any]]:
        conn = await self.get_connection()
        async with conn.execute("SELECT * FROM posts WHERE post_id = ?", (post_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def delete_post(self, post_id: int):
        conn = await self.get_connection()
        await conn.execute("DELETE FROM posts WHERE post_id = ?", (post_id,))
        await conn.commit()

    async def get_posts_by_status(self, status: str) -> List[Dict[str, Any]]:
        conn = await self.get_connection()
        async with conn.execute("SELECT * FROM posts WHERE status = ?", (status,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_scheduled_posts_by_user(self, user_id: int) -> List[Dict[str, Any]]:
        conn = await self.get_connection()
        async with conn.execute("""
            SELECT p.*, c.title as channel_title 
            FROM posts p
            JOIN channels c ON p.channel_id = c.channel_id
            WHERE p.user_id = ? AND p.status = 'scheduled'
            ORDER BY p.scheduled_at ASC
        """, (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_history_posts(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        conn = await self.get_connection()
        async with conn.execute("""
            SELECT p.*, c.title as channel_title 
            FROM posts p
            JOIN channels c ON p.channel_id = c.channel_id
            WHERE p.user_id = ? AND p.status = 'posted'
            ORDER BY p.created_at DESC
            LIMIT ?
        """, (user_id, limit)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ------------------- Media Groups (Albums) -------------------
    async def add_post_media(self, post_id: int, media_type: str, file_id: str, 
                             position: int = 0, has_spoiler: bool = False) -> int:
        conn = await self.get_connection()
        async with conn.execute("""
            INSERT INTO post_media (post_id, media_type, file_id, position, has_spoiler)
            VALUES (?, ?, ?, ?, ?)
        """, (post_id, media_type, file_id, position, 1 if has_spoiler else 0)) as cursor:
            media_id = cursor.lastrowid
            await conn.commit()
            return media_id

    async def get_post_media(self, post_id: int) -> List[Dict[str, Any]]:
        conn = await self.get_connection()
        async with conn.execute("""
            SELECT * FROM post_media 
            WHERE post_id = ? 
            ORDER BY position ASC, media_id ASC
        """, (post_id,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def clear_post_media(self, post_id: int):
        conn = await self.get_connection()
        await conn.execute("DELETE FROM post_media WHERE post_id = ?", (post_id,))
        await conn.commit()

    async def delete_post_media(self, media_id: int):
        conn = await self.get_connection()
        await conn.execute("DELETE FROM post_media WHERE media_id = ?", (media_id,))
        await conn.commit()

    # ------------------- Sent Posts & History -------------------
    async def add_sent_post(self, channel_id: int, message_id: int, post_id: int):
        conn = await self.get_connection()
        await conn.execute("""
            INSERT OR REPLACE INTO sent_posts (channel_id, message_id, post_id)
            VALUES (?, ?, ?)
        """, (channel_id, message_id, post_id))
        await conn.commit()

    async def get_post_by_sent_msg(self, channel_id: int, message_id: int) -> Optional[Dict[str, Any]]:
        conn = await self.get_connection()
        async with conn.execute("""
            SELECT p.* FROM posts p
            JOIN sent_posts sp ON p.post_id = sp.post_id
            WHERE sp.channel_id = ? AND sp.message_id = ?
        """, (channel_id, message_id)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_sent_messages_by_post_id(self, post_id: int) -> List[Dict[str, Any]]:
        conn = await self.get_connection()
        async with conn.execute("""
            SELECT channel_id, message_id FROM sent_posts WHERE post_id = ?
        """, (post_id,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ------------------- Reactions & Voting -------------------
    async def add_vote(self, post_id: int, user_id: int, reaction: str) -> dict:
        """
        Adds, updates, or removes user's vote for a reaction.
        Returns the updated count of all reactions for this post.
        """
        conn = await self.get_connection()
        async with conn.execute(
            "SELECT reaction FROM votes WHERE post_id = ? AND user_id = ?", 
            (post_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            
        if row:
            existing_reaction = row[0]
            if existing_reaction == reaction:
                # User clicked the same reaction -> toggle off (remove)
                await conn.execute("DELETE FROM votes WHERE post_id = ? AND user_id = ?", (post_id, user_id))
            else:
                # User clicked different reaction -> update
                await conn.execute("UPDATE votes SET reaction = ? WHERE post_id = ? AND user_id = ?", (reaction, post_id, user_id))
        else:
            # New vote
            await conn.execute("INSERT INTO votes (post_id, user_id, reaction) VALUES (?, ?, ?)", (post_id, user_id, reaction))
        
        await conn.commit()
        return await self.get_post_reactions_count(post_id)

    async def get_post_reactions_count(self, post_id: int) -> dict:
        conn = await self.get_connection()
        async with conn.execute("SELECT reactions_json FROM posts WHERE post_id = ?", (post_id,)) as cursor:
            row = await cursor.fetchone()
            
        if not row or not row[0]:
            return {}
        
        try:
            reactions_list = json.loads(row[0])
        except Exception:
            return {}

        counts = {r: 0 for r in reactions_list}
        
        async with conn.execute("""
            SELECT reaction, COUNT(*) as cnt 
            FROM votes 
            WHERE post_id = ? 
            GROUP BY reaction
        """, (post_id,)) as cursor:
            for r_row in await cursor.fetchall():
                react = r_row[0]
                count = r_row[1]
                if react in counts:
                    counts[react] = count
                
        return counts
