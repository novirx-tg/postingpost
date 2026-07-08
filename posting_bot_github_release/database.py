import sqlite3
import json
from datetime import datetime
import os

class Database:
    def __init__(self, db_path="posting_bot.db"):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Channels table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS channels (
                    channel_id INTEGER PRIMARY KEY,
                    title TEXT,
                    username TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # User channels link table (allows multiple admins to add the same channel)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_channels (
                    user_id INTEGER,
                    channel_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, channel_id),
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE
                )
            """)
            
            # Posts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS posts (
                    post_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    channel_id INTEGER,
                    content_type TEXT, -- 'text', 'photo', 'video', 'document', 'audio', 'sticker', 'voice', 'animation'
                    text TEXT,
                    media_file_id TEXT,
                    buttons_json TEXT, -- JSON array: [[{"text": "Btn 1", "url": "https://..."}, ...], ...]
                    reactions_json TEXT, -- JSON array of reaction emojis: ["👍", "👎"]
                    message_effect_id TEXT, -- ID of Telegram message visual effect
                    parse_mode TEXT DEFAULT 'HTML', -- 'HTML' or 'MarkdownV2' or 'Markdown'
                    status TEXT DEFAULT 'draft', -- 'draft', 'scheduled', 'posted', 'failed'
                    scheduled_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE
                )
            """)
            
            # Sent posts mapping table (links telegram message in channel to post_id for voting)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sent_posts (
                    channel_id INTEGER,
                    message_id INTEGER,
                    post_id INTEGER,
                    PRIMARY KEY (channel_id, message_id),
                    FOREIGN KEY (post_id) REFERENCES posts(post_id) ON DELETE CASCADE
                )
            """)
            
            # Votes table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS votes (
                    post_id INTEGER,
                    user_id INTEGER,
                    reaction TEXT,
                    PRIMARY KEY (post_id, user_id),
                    FOREIGN KEY (post_id) REFERENCES posts(post_id) ON DELETE CASCADE
                )
            """)
            
            # Upgrade schema dynamically if posts column is missing
            try:
                cursor.execute("ALTER TABLE posts ADD COLUMN message_effect_id TEXT")
            except sqlite3.OperationalError:
                pass
                
            try:
                cursor.execute("ALTER TABLE posts ADD COLUMN parse_mode TEXT DEFAULT 'HTML'")
            except sqlite3.OperationalError:
                pass
                
            conn.commit()

    def add_user(self, user_id: int, username: str, first_name: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (user_id, username, first_name)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name
            """, (user_id, username, first_name))
            conn.commit()

    def add_channel(self, channel_id: int, title: str, username: str, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Add to channels if not exists
            cursor.execute("""
                INSERT INTO channels (channel_id, title, username)
                VALUES (?, ?, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    title = excluded.title,
                    username = excluded.username
            """, (channel_id, title, username))
            
            # Link to user
            cursor.execute("""
                INSERT OR IGNORE INTO user_channels (user_id, channel_id)
                VALUES (?, ?)
            """, (user_id, channel_id))
            conn.commit()

    def remove_channel(self, channel_id: int, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM user_channels
                WHERE user_id = ? AND channel_id = ?
            """, (user_id, channel_id))
            conn.commit()

    def get_channels_by_user(self, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT c.channel_id, c.title, c.username 
                FROM channels c
                JOIN user_channels uc ON c.channel_id = uc.channel_id
                WHERE uc.user_id = ?
            """, (user_id,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def create_post(self, user_id: int, channel_id: int, content_type: str = 'text', 
                    text: str = None, media_file_id: str = None, buttons_json: str = None, 
                    reactions_json: str = None, status: str = 'draft', scheduled_at: str = None,
                    message_effect_id: str = None, parse_mode: str = 'HTML') -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO posts (user_id, channel_id, content_type, text, media_file_id, buttons_json, reactions_json, message_effect_id, parse_mode, status, scheduled_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, channel_id, content_type, text, media_file_id, buttons_json, reactions_json, message_effect_id, parse_mode, status, scheduled_at))
            conn.commit()
            return cursor.lastrowid

    def update_post(self, post_id: int, **kwargs):
        if not kwargs:
            return
        fields = []
        values = []
        for key, val in kwargs.items():
            fields.append(f"{key} = ?")
            values.append(val)
        values.append(post_id)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = f"UPDATE posts SET {', '.join(fields)} WHERE post_id = ?"
            cursor.execute(query, tuple(values))
            conn.commit()

    def get_post(self, post_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM posts WHERE post_id = ?", (post_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_posts_by_status(self, status: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM posts WHERE status = ?", (status,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_scheduled_posts_by_user(self, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.*, c.title as channel_title 
                FROM posts p
                JOIN channels c ON p.channel_id = c.channel_id
                WHERE p.user_id = ? AND p.status = 'scheduled'
                ORDER BY p.scheduled_at ASC
            """, (user_id,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def add_sent_post(self, channel_id: int, message_id: int, post_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO sent_posts (channel_id, message_id, post_id)
                VALUES (?, ?, ?)
            """, (channel_id, message_id, post_id))
            conn.commit()

    def get_post_by_sent_msg(self, channel_id: int, message_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.* FROM posts p
                JOIN sent_posts sp ON p.post_id = sp.post_id
                WHERE sp.channel_id = ? AND sp.message_id = ?
            """, (channel_id, message_id))
            row = cursor.fetchone()
            return dict(row) if row else None

    def add_vote(self, post_id: int, user_id: int, reaction: str) -> dict:
        """
        Adds, updates, or removes user's vote for a reaction.
        Returns the updated count of all reactions for this post.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Check existing vote
            cursor.execute("SELECT reaction FROM votes WHERE post_id = ? AND user_id = ?", (post_id, user_id))
            row = cursor.fetchone()
            
            if row:
                existing_reaction = row[0]
                if existing_reaction == reaction:
                    # User clicked the same reaction -> toggle off (remove)
                    cursor.execute("DELETE FROM votes WHERE post_id = ? AND user_id = ?", (post_id, user_id))
                else:
                    # User clicked different reaction -> update
                    cursor.execute("UPDATE votes SET reaction = ? WHERE post_id = ? AND user_id = ?", (reaction, post_id, user_id))
            else:
                # New vote
                cursor.execute("INSERT INTO votes (post_id, user_id, reaction) VALUES (?, ?, ?)", (post_id, user_id, reaction))
            
            conn.commit()
            
        return self.get_post_reactions_count(post_id)

    def get_post_reactions_count(self, post_id: int) -> dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Fetch the defined reactions list first
            cursor.execute("SELECT reactions_json FROM posts WHERE post_id = ?", (post_id,))
            row = cursor.fetchone()
            if not row or not row[0]:
                return {}
            
            reactions_list = json.loads(row[0])
            counts = {r: 0 for r in reactions_list}
            
            # Count votes from DB
            cursor.execute("""
                SELECT reaction, COUNT(*) as cnt 
                FROM votes 
                WHERE post_id = ? 
                GROUP BY reaction
            """, (post_id,))
            
            for r_row in cursor.fetchall():
                react = r_row[0]
                count = r_row[1]
                if react in counts:
                    counts[react] = count
                    
            return counts
