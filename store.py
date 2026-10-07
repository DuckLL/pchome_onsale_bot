"""SQLite state: who watches which product, and each product's last price.

The schema is the one the `dataset` library created in 2022, kept as is so
the old bot.db opens unchanged. `monitor` has one row per (user, pid); `prod`
one row per product with the last seen price and a count of failed checks.
"""

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS monitor (
    id INTEGER NOT NULL, user BIGINT, pid TEXT, name TEXT, PRIMARY KEY (id));
CREATE TABLE IF NOT EXISTS prod (
    id INTEGER NOT NULL, pid TEXT, last_price BIGINT, name TEXT, error BIGINT,
    PRIMARY KEY (id));
CREATE INDEX IF NOT EXISTS ix_monitor_00d7853e5761de29 ON monitor (user, pid);
CREATE INDEX IF NOT EXISTS ix_prod_e411f5c208942f77 ON prod (pid);
"""


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    # --- reads ---------------------------------------------------------

    def watched_pids(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT DISTINCT pid FROM monitor ORDER BY pid")]

    def watchers(self, pid: str) -> list[int]:
        return [r[0] for r in self.db.execute(
            "SELECT DISTINCT user FROM monitor WHERE pid = ? ORDER BY user", (pid,))]

    def product(self, pid: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT pid, name, last_price, error FROM prod WHERE pid = ?", (pid,)).fetchone()

    def items(self, user: int) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT pid, name FROM monitor WHERE user = ? ORDER BY id", (user,)).fetchall()

    def item(self, user: int, pid: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT pid, name FROM monitor WHERE user = ? AND pid = ?", (user, pid)).fetchone()

    # --- writes --------------------------------------------------------

    def watch(self, user: int, pid: str, name: str, price: int) -> None:
        """Start watching; the current price becomes the baseline for every watcher."""
        with self.db:
            if not self.item(user, pid):
                self.db.execute("INSERT INTO monitor (user, pid, name) VALUES (?, ?, ?)",
                                (user, pid, name))
            self._set_price(pid, price, name)

    def unwatch(self, user: int, pid: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM monitor WHERE user = ? AND pid = ?", (user, pid))
            if not self.watchers(pid):
                self.db.execute("DELETE FROM prod WHERE pid = ?", (pid,))

    def record_price(self, pid: str, price: int, name: str) -> None:
        with self.db:
            self._set_price(pid, price, name)

    def record_error(self, pid: str) -> None:
        with self.db:
            self.db.execute("UPDATE prod SET error = COALESCE(error, 0) + 1 WHERE pid = ?",
                            (pid,))

    def remove_product(self, pid: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM monitor WHERE pid = ?", (pid,))
            self.db.execute("DELETE FROM prod WHERE pid = ?", (pid,))

    def _set_price(self, pid: str, price: int, name: str) -> None:
        if self.product(pid):
            self.db.execute("UPDATE prod SET last_price = ?, error = 0 WHERE pid = ?", (price, pid))
        else:
            self.db.execute(
                "INSERT INTO prod (pid, last_price, name, error) VALUES (?, ?, ?, 0)",
                (pid, price, name))
