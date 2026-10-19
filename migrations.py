import aiosqlite
import logging

logger = logging.getLogger(__name__)

MIGRATIONS = [
    # (номер версии, SQL)
    (1, """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS channels (
            channel_id INTEGER PRIMARY KEY,
            title TEXT,
            username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS user_channels (
            user_id INTEGER,
            channel_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, channel_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE
        );
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
        );
        CREATE TABLE IF NOT EXISTS sent_posts (
            channel_id INTEGER,
            message_id INTEGER,
            post_id INTEGER,
            PRIMARY KEY (channel_id, message_id),
            FOREIGN KEY (post_id) REFERENCES posts(post_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS votes (
            post_id INTEGER,
            user_id INTEGER,
            reaction TEXT,
            PRIMARY KEY (post_id, user_id),
            FOREIGN KEY (post_id) REFERENCES posts(post_id) ON DELETE CASCADE
        );
    """),
    (2, """
        ALTER TABLE posts ADD COLUMN table_matrix_json TEXT;
        ALTER TABLE posts ADD COLUMN from_chat_id BIGINT;
        ALTER TABLE posts ADD COLUMN source_message_id BIGINT;
    """),
    (3, """
        CREATE TABLE IF NOT EXISTS post_media (
            media_id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            media_type TEXT NOT NULL,
            file_id TEXT NOT NULL,
            position INTEGER DEFAULT 0,
            has_spoiler BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (post_id) REFERENCES posts(post_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_post_media_post_id ON post_media(post_id);
        ALTER TABLE posts ADD COLUMN show_caption_above_media BOOLEAN DEFAULT 0;
        ALTER TABLE posts ADD COLUMN has_spoiler BOOLEAN DEFAULT 0;
        ALTER TABLE posts ADD COLUMN link_preview_options_json TEXT;
    """),
    (4, """
        ALTER TABLE posts ADD COLUMN star_count INTEGER DEFAULT 0;
        ALTER TABLE posts ADD COLUMN poll_data_json TEXT;
    """),
]

async def get_schema_version(db: aiosqlite.Connection) -> int:
    await db.execute("CREATE TABLE IF NOT EXISTS schema_version (v INTEGER NOT NULL)")
    cur = await db.execute("SELECT v FROM schema_version LIMIT 1")
    row = await cur.fetchone()
    if row is None:
        # Check legacy schema_migrations table if database was created by previous version
        legacy_cur = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'")
        if await legacy_cur.fetchone():
            ver_cur = await db.execute("SELECT MAX(version) FROM schema_migrations")
            ver_row = await ver_cur.fetchone()
            legacy_v = ver_row[0] if ver_row and ver_row[0] is not None else 0
            await db.execute("INSERT INTO schema_version (v) VALUES (?)", (legacy_v,))
            await db.commit()
            return legacy_v
        await db.execute("INSERT INTO schema_version (v) VALUES (0)")
        await db.commit()
        return 0
    return row[0]

async def migrate(db_path: str):
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        current = await get_schema_version(db)
        for version, sql in MIGRATIONS:
            if version > current:
                # Handle possible already existing columns gracefully
                statements = [s.strip() for s in sql.strip().split(";") if s.strip()]
                for statement in statements:
                    try:
                        await db.execute(statement)
                    except aiosqlite.OperationalError as oe:
                        if "duplicate column name" in str(oe).lower():
                            pass
                        else:
                            raise oe
                await db.execute("UPDATE schema_version SET v = ?", (version,))
                await db.commit()
                print(f"[migrate] applied v{version}")
                logger.info(f"[migrate] applied v{version}")
