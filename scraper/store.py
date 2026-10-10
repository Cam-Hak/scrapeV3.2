import sqlite3
from datetime import datetime
from pathlib import Path

from .recipe import Recipe

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipe (
    a_id INTEGER PRIMARY KEY,
    json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path, readonly=False):
        if readonly:
            # a scrape run only reads recipes, so it can never change, lock or create the file
            self.db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
            return
        self.db = sqlite3.connect(path)
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
        self.db.commit()
        return gone > 0

    def close(self):
        self.db.close()
