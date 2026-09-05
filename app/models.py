"""
SahyogSutra Database Models & Migration Module.
Sets up database tables, indexes, and handles data migrations.
"""

import ast
import logging
from typing import Any

logger = logging.getLogger(__name__)

INIT_DDL_STATEMENTS = [
    # OTP Storage Table
    """
    CREATE TABLE IF NOT EXISTS otp_verifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        identifier TEXT NOT NULL,
        purpose TEXT NOT NULL,
        otp_hash TEXT NOT NULL,
        expires_at INTEGER NOT NULL,
        attempts INTEGER DEFAULT 0,
        used_at INTEGER DEFAULT NULL,
        created_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_otp_lookup ON otp_verifications(identifier, purpose, used_at)",

    # Relational Messages Table
    """
    CREATE TABLE IF NOT EXISTS messages (
        eventid INTEGER,
        username TEXT(20),
        message TEXT,
        time TEXT,
        srno INTEGER PRIMARY KEY AUTOINCREMENT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_messages_eventid ON messages(eventid, srno)",

    # Event detail performance indexes
    "CREATE INDEX IF NOT EXISTS idx_eventdetail_eventid ON eventdetail(eventid)",
    "CREATE INDEX IF NOT EXISTS idx_eventdetail_username ON eventdetail(username)",
    "CREATE INDEX IF NOT EXISTS idx_eventdetail_category ON eventdetail(category)",
    "CREATE INDEX IF NOT EXISTS idx_eventdetail_likes ON eventdetail(likes)",
]


async def initialize_schema(db):
    """Ensures necessary tables and indexes exist in the database."""
    for stmt in INIT_DDL_STATEMENTS:
        try:
            await db.execute(stmt)
        except Exception as e:
            logger.debug("Schema init statement notice: %s (%s)", stmt.strip()[:40], e)
    await db.commit()


async def migrate_legacy_messages(db):
    """
    Safely migrates serialized Python tuples from legacy messages2 table
    into the normalized relational messages table.
    """
    try:
        # Check if messages2 exists
        table_check = await db.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages2'"
        )
        if not table_check:
            return

        rows = await db.fetchall("SELECT eventid, msgs FROM messages2")
        if not rows:
            return

        # Check existing count in messages
        count_row = await db.fetchone("SELECT COUNT(*) as count FROM messages")
        existing_count = count_row["count"] if count_row else 0

        # If messages already has records, migration likely already ran
        if existing_count > 0:
            return

        migrated_total = 0
        for row in rows:
            eventid = row["eventid"]
            msgs_str = row["msgs"]
            if not msgs_str:
                continue

            try:
                parsed_msgs = ast.literal_eval(msgs_str)
                for item in parsed_msgs:
                    if len(item) >= 3:
                        uname, text, timestamp = item[0], item[1], item[2]
                        await db.execute(
                            "INSERT INTO messages(eventid, username, message, time) VALUES (?, ?, ?, ?)",
                            (eventid, uname, text, timestamp)
                        )
                        migrated_total += 1
            except Exception as parse_err:
                logger.warning("Failed parsing messages for event %s: %s", eventid, parse_err)

        await db.commit()
        if migrated_total > 0:
            logger.info("Migrated %d legacy messages into relational messages table.", migrated_total)
    except Exception as e:
        logger.error("Error during legacy message migration: %s", e)

