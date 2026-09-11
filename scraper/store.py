import sqlite3
from datetime import datetime

from .recipe import Recipe

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipe (
    a_id INTEGER PRIMARY KEY,
    json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS failure (
    a_id INTEGER PRIMARY KEY,
    streak INTEGER NOT NULL DEFAULT 0
);
"""


class Store:
    def __init__(self, path, max_failures=3):
        self.db = sqlite3.connect(path)
        self.max_failures = max_failures
        self.db.executescript(SCHEMA)
        self.db.commit()

    def get_recipe(self, a_id):
        row = self.db.execute("SELECT json FROM recipe WHERE a_id = ?", (a_id,)).fetchone()
        return Recipe.from_json(row[0]) if row else None

    def save_recipe(self, a_id, recipe):
        self.db.execute(
            "REPLACE INTO recipe (a_id, json, created_at) VALUES (?, ?, ?)",
            (a_id, recipe.to_json(), datetime.now().isoformat()),
        )
        self.db.commit()

    def remove_recipe(self, a_id):
        gone = self.db.execute("DELETE FROM recipe WHERE a_id = ?", (a_id,)).rowcount
        self.db.execute("DELETE FROM failure WHERE a_id = ?", (a_id,))
        self.db.commit()
        return gone > 0

    def record_result(self, a_id, ok):
        streak = 0 if ok else self._streak(a_id) + 1
        self.db.execute("REPLACE INTO failure (a_id, streak) VALUES (?, ?)", (a_id, streak))
        self.db.commit()

    def is_failed(self, a_id):
        return self._streak(a_id) >= self.max_failures

    def clear_failures(self):
        self.db.execute("DELETE FROM failure")
        self.db.commit()

    def _streak(self, a_id):
        row = self.db.execute("SELECT streak FROM failure WHERE a_id = ?", (a_id,)).fetchone()
        return row[0] if row else 0

    def close(self):
        self.db.close()
