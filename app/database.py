"""
SahyogSutra Database Module.
Provides a strictly bounded connection pool for SQLiteCloud,
an async-safe database dependency, and lightweight query helpers.
"""

import asyncio
import logging
import os
import queue
import threading
from typing import Any, List, Optional, Tuple

import sqlitecloud as sq

from app.config import DB_POOL_MAX, DB_POOL_TIMEOUT, SQLITECLOUD_URL

logger = logging.getLogger(__name__)

# Strict bounded queue for idle connections
_idle_pool: queue.Queue = queue.Queue(maxsize=DB_POOL_MAX)
_open_connections: int = 0
_pool_lock: threading.Lock = threading.Lock()
_closed = False

# Dedicated bounded thread pool for blocking SQLiteCloud driver calls
# 3 threads matches max 3 DB connections
_db_executor = None

def get_db_executor():
    global _db_executor
    if _db_executor is None:
        from concurrent.futures import ThreadPoolExecutor
        _db_executor = ThreadPoolExecutor(max_workers=DB_POOL_MAX, thread_name_prefix="DBWorker")
    return _db_executor


def _open_raw_connection():
    """Opens a single, properly configured SQLiteCloud connection."""
    if not SQLITECLOUD_URL:
        raise ValueError("SQLITECLOUD URL environment variable is not configured!")

    db = sq.connect(SQLITECLOUD_URL)
    db.row_factory = sq.Row
    return db


def init_db_pool(eager_count: int = 1):
    """Initializes the connection pool with a conservative initial connection count."""
    global _open_connections, _closed
    _closed = False
    with _pool_lock:
        to_open = min(eager_count, DB_POOL_MAX)
        for _ in range(to_open):
            try:
                conn = _open_raw_connection()
                _idle_pool.put_nowait(conn)
                _open_connections += 1
            except Exception as e:
                logger.error("Failed to pre-open DB connection: %s", e)
                break
    logger.info("DB pool initialized: %d/%d connections", _open_connections, DB_POOL_MAX)


def close_db_pool():
    """Drains and closes all open database connections."""
    global _open_connections, _closed, _db_executor
    _closed = True
    with _pool_lock:
        while not _idle_pool.empty():
            try:
                conn = _idle_pool.get_nowait()
                conn.close()
            except Exception:
                pass
        _open_connections = 0

    if _db_executor:
        _db_executor.shutdown(wait=False)
        _db_executor = None
    logger.info("DB pool shut down completely.")


def acquire_connection(timeout: int = DB_POOL_TIMEOUT):
    """
    Acquires one connection from the pool.
    Reuses an idle connection, or creates a new one up to DB_POOL_MAX.
    Blocks up to timeout seconds if all connections are in use.
    """
    global _open_connections, _closed
    if _closed:
        init_db_pool(eager_count=1)

    # 1. Try to grab an idle connection immediately
    try:
        return _idle_pool.get_nowait()
    except queue.Empty:
        pass

    # 2. Check if we can open a new connection under the cap
    can_open = False
    with _pool_lock:
        if _open_connections < DB_POOL_MAX:
            _open_connections += 1
            can_open = True

    if can_open:
        try:
            return _open_raw_connection()
        except Exception:
            with _pool_lock:
                _open_connections -= 1
            raise

    # 3. Wait for an existing connection to be returned
    try:
        return _idle_pool.get(block=True, timeout=timeout)
    except queue.Empty:
        raise RuntimeError(
            f"DB connection pool exhausted ({DB_POOL_MAX} connections in use). "
            f"Wait timed out after {timeout} seconds."
        )


def release_connection(conn, discard: bool = False):
    """Returns a connection to the pool or closes it if discarded/closed."""
    global _open_connections
    if conn is None:
        return

    if _closed or discard:
        try:
            conn.close()
        except Exception:
            pass
        with _pool_lock:
            _open_connections = max(0, _open_connections - 1)
        return

    try:
        conn.commit()
    except Exception:
        pass

    try:
        _idle_pool.put_nowait(conn)
    except queue.Full:
        # Should not happen with correct accounting, but safely close if so
        try:
            conn.close()
        except Exception:
            pass
        with _pool_lock:
            _open_connections = max(0, _open_connections - 1)


class AsyncDB:
    """Async wrapper around a borrowed SQLiteCloud connection."""

    def __init__(self, conn):
        self._conn = conn
        self._cursor = conn.cursor()
        self._loop = asyncio.get_running_loop()
        self._executor = get_db_executor()
        self._released = False
        self._dirty = False

    async def _run(self, fn, *args):
        return await self._loop.run_in_executor(self._executor, fn, *args)

    async def execute(self, query: str, params: tuple = ()):
        def _do():
            return self._cursor.execute(query, params)
        await self._run(_do)
        self._dirty = True
        return self

    async def fetchone(self, query: Optional[str] = None, params: tuple = ()):
        def _do():
            if query is not None:
                self._cursor.execute(query, params)
            return self._cursor.fetchone()
        row = await self._run(_do)
        return dict(row) if row is not None else None

    async def fetchall(self, query: Optional[str] = None, params: tuple = ()) -> List[dict]:
        def _do():
            if query is not None:
                self._cursor.execute(query, params)
            rows = self._cursor.fetchall()
            return [dict(r) for r in rows] if rows else []
        return await self._run(_do)

    async def commit(self):
        if self._dirty:
            def _do():
                self._conn.commit()
            await self._run(_do)
            self._dirty = False

    def close(self, discard: bool = False):
        if not self._released:
            self._released = True
            release_connection(self._conn, discard=discard)


async def get_db():
    """FastAPI async dependency yielding an AsyncDB instance."""
    loop = asyncio.get_running_loop()
    conn = await loop.run_in_executor(get_db_executor(), acquire_connection)
    db = AsyncDB(conn)
    discard = False
    try:
        yield db
        if db._dirty:
            await db.commit()
    except Exception:
        discard = False  # Keep connection unless it's a fatal broken socket
        raise
    finally:
        db.close(discard=discard)


async def run_query(query: str, params: tuple = (), fetchmode: str = "all") -> Any:
    """Executes a single query asynchronously from the pool and automatically returns connection."""
    loop = asyncio.get_running_loop()

    def _execute():
        conn = acquire_connection()
        try:
            c = conn.cursor()
            c.execute(query, params)
            if fetchmode == "all":
                res = [dict(r) for r in c.fetchall()] if c.fetchall else []
            elif fetchmode == "one":
                row = c.fetchone()
                res = dict(row) if row is not None else None
            else:
                res = None
            conn.commit()
            return res
        finally:
            release_connection(conn)

    return await loop.run_in_executor(get_db_executor(), _execute)


async def run_queries_parallel(*queries) -> list:
    """Executes multiple (query, params, fetchmode) tuples concurrently."""
    tasks = [run_query(q, p, f) for q, p, f in queries]
    return await asyncio.gather(*tasks)


class SyncDBContext:
    """Synchronous context manager for non-async contexts (e.g. Socket.IO sync code)."""
    def __init__(self):
        self.conn = None
        self.cursor = None

    def __enter__(self):
        self.conn = acquire_connection()
        self.cursor = self.conn.cursor()
        return self.conn, self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            release_connection(self.conn, discard=(exc_type is not None))
