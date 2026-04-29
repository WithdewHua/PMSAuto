import json
import pickle
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class SQLiteCache:
    def __init__(
        self, db_path, table_name="cache", timeout=30, legacy_pickle_paths=None
    ):
        self.db_path = Path(db_path)
        self.table_name = table_name
        self.timeout = timeout
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._migrate_legacy_pickles(legacy_pickle_paths or [])

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=self.timeout)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(f"PRAGMA busy_timeout={self.timeout * 1000}")
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _migrate_legacy_pickles(self, legacy_pickle_paths):
        migration_key = f"{self.table_name}_legacy_pickle_migrated"
        with self._connect() as conn:
            if conn.execute(
                "SELECT 1 FROM cache_meta WHERE key = ? LIMIT 1", (migration_key,)
            ).fetchone():
                return

        legacy_cache = None
        for path in legacy_pickle_paths:
            path = Path(path)
            if not path.exists() or path.stat().st_size == 0:
                continue
            try:
                with open(path, "rb") as f:
                    legacy_cache = pickle.load(f)
                if isinstance(legacy_cache, dict):
                    break
            except (EOFError, OSError, pickle.UnpicklingError, ValueError):
                continue
        if not isinstance(legacy_cache, dict):
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO cache_meta (key, value) VALUES (?, ?)",
                    (migration_key, "1"),
                )
                conn.commit()
            return

        with self._connect() as conn:
            for key, value in legacy_cache.items():
                payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                conn.execute(
                    f"""
                    INSERT OR IGNORE INTO {self.table_name} (key, value, updated_at)
                    VALUES (?, ?, strftime('%s', 'now'))
                    """,
                    (key, payload),
                )
            conn.execute(
                "INSERT OR REPLACE INTO cache_meta (key, value) VALUES (?, ?)",
                (migration_key, "1"),
            )
            conn.commit()

    def get(self, key, default=None):
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT value FROM {self.table_name} WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return default
        return json.loads(row[0])

    def set(self, key, value):
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {self.table_name} (key, value, updated_at)
                VALUES (?, ?, strftime('%s', 'now'))
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, payload),
            )
            conn.commit()

    def delete(self, key):
        with self._connect() as conn:
            cursor = conn.execute(
                f"DELETE FROM {self.table_name} WHERE key = ?", (key,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def contains(self, key):
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT 1 FROM {self.table_name} WHERE key = ? LIMIT 1", (key,)
            ).fetchone()
        return row is not None

    def update(self, key, value=None):
        if isinstance(key, dict):
            for item_key, item_value in key.items():
                self.set(item_key, item_value)
            return
        self.set(key, value)

    def pop(self, key, default=None):
        value = self.get(key, default)
        self.delete(key)
        return value

    def items(self):
        with self._connect() as conn:
            rows = conn.execute(f"SELECT key, value FROM {self.table_name}").fetchall()
        return [(key, json.loads(value)) for key, value in rows]

    def as_dict(self):
        return dict(self.items())

    def __contains__(self, key):
        return self.contains(key)

    def __getitem__(self, key):
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def __setitem__(self, key, value):
        self.set(key, value)

    def __delitem__(self, key):
        if not self.delete(key):
            raise KeyError(key)
