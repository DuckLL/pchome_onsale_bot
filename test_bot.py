import asyncio
import datetime as dt
import re
import sqlite3

import httpx
import pytest
from telegram.error import BadRequest, Forbidden

import bot
import pchome
from store import Store

# Exactly what the `dataset` library created in 2022 (copied from the live bot.db).
OLD_DDL = """
CREATE TABLE monitor (
	id INTEGER NOT NULL,
	user BIGINT,
	pid TEXT,
	name TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE prod (
	id INTEGER NOT NULL,
	pid TEXT,
	last_price BIGINT,
	name TEXT, error BIGINT,
	PRIMARY KEY (id)
);
CREATE INDEX ix_monitor_00d7853e5761de29 ON monitor (user, pid);
CREATE INDEX ix_prod_e411f5c208942f77 ON prod (pid);
"""

A, B = "DYAQF4-A900JIDAU", "DAAC0X-A9009ZAA6"


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "bot.db"
    con = sqlite3.connect(path)
    con.executescript(OLD_DDL)
    con.executemany("INSERT INTO monitor (user, pid, name) VALUES (?, ?, ?)",
                    [(1, A, "earbuds"), (2, A, "earbuds"), (1, B, "bags")])
    con.executemany("INSERT INTO prod (pid, last_price, name, error) VALUES (?, ?, ?, ?)",
                    [(A, 3280, "earbuds", 0), (B, 69, "bags", 0),
                     ("ORPHAN-000000000", 1, "old", 0)])
    con.commit()
    con.close()
    s = Store(str(path))
    yield s
    s.close()


def prices(**by_pid):
    return lambda pid: (pchome.Product(pid, "x", by_pid[pid])
                        if by_pid.get(pid) is not None else None)


def run(coro):
    return asyncio.run(coro)


def test_old_database_opens_and_reads(store):
    assert store.watched_pids() == sorted([A, B])
    assert store.watchers(A) == [1, 2]
    assert [r["pid"] for r in store.items(1)] == [A, B]


def test_price_drop_notifies_every_watcher_and_updates_baseline(store):
    notices = run(bot.check_prices(store, prices(**{A: 2990, B: 69})))
    assert len(notices) == 1
    assert notices[0].users == [1, 2]
    assert "3280 -&gt; 2990" in notices[0].html and A in notices[0].html
    assert store.product(A)["last_price"] == 2990


def test_price_rise_is_silent_but_recorded(store):
    assert run(bot.check_prices(store, prices(**{A: 3500, B: 69}))) == []
    assert store.product(A)["last_price"] == 3500


def test_one_broken_product_does_not_stop_the_rest(store):
    def fetch(pid):
        if pid == B:
            raise KeyError("Price")
        return pchome.Product(pid, "x", 2990)
    notices = run(bot.check_prices(store, fetch))
    assert [n.users for n in notices] == [[1, 2]]
    assert store.product(A)["last_price"] == 2990


def test_check_mode_writes_nothing(store):
    notices = run(bot.check_prices(store, prices(**{A: 2990, B: None}), write=False))
    assert len(notices) == 1
    assert store.product(A)["last_price"] == 3280
    assert store.product(B)["error"] == 0


def test_failures_count_up_and_success_resets(store):
    for _ in range(3):
        run(bot.check_prices(store, prices(**{A: 3280, B: None})))
    assert store.product(B)["error"] == 3
    run(bot.check_prices(store, prices(**{A: 3280, B: 69})))
    assert store.product(B)["error"] == 0


def test_product_gone_too_long_is_removed_with_notice(store):
    store.db.execute("UPDATE prod SET error = ? WHERE pid = ?", (bot.MAX_ERRORS, B))
    store.db.commit()
    assert run(bot.check_prices(store, prices(**{A: 3280, B: None}))) == []
    assert store.product(B)["error"] == bot.MAX_ERRORS + 1

    notices = run(bot.check_prices(store, prices(**{A: 3280, B: None})))
    assert [n.users for n in notices] == [[1]]
    assert "已下架" in notices[0].text
    assert store.product(B) is None and B not in store.watched_pids()


def test_watch_is_idempotent_and_resets_baseline(store):
    store.watch(1, A, "earbuds", 3000)
    store.watch(1, A, "earbuds", 3000)
    assert store.watchers(A) == [1, 2]
    assert store.product(A)["last_price"] == 3000


def test_unwatch_drops_product_with_its_last_watcher(store):
    store.unwatch(1, B)
    assert store.product(B) is None
    store.unwatch(1, A)
    assert store.product(A) is not None  # user 2 still watches it


class FakeBot:
    def __init__(self, fail):
        self.fail, self.sent = fail, []

    async def send_message(self, chat_id, text, **kw):
        err = self.fail.get((chat_id, "parse_mode" in kw))
        if err:
            raise err
        self.sent.append((chat_id, text))


def test_send_survives_blocked_user_and_bad_markup():
    notice = bot.Notice([1, 2, 3], "<b>html</b>", "plain")
    fake = FakeBot({(1, True): Forbidden("blocked"), (2, True): BadRequest("can't parse")})
    run(bot.send(fake, notice))
    assert fake.sent == [(2, "plain"), (3, "<b>html</b>")]


def test_names_are_escaped():
    notice = run(bot.check_prices(_one(A, "a<b>&c", 100), prices(**{A: 90})))[0]
    assert "a&lt;b&gt;&amp;c" in notice.html


def _one(pid, name, price):
    s = Store(":memory:")
    s.watch(7, pid, name, price)
    return s


def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_parses_product():
    def handler(req):
        assert A in str(req.url) and "fields=Name,Price" in str(req.url)
        return httpx.Response(200, json={f"{A}-000": {"Name": "n", "Price": {"P": 3280}}})
    assert pchome.fetch(A, client=mock_client(handler), sleep=lambda s: None) == \
        pchome.Product(A, "n", 3280)


def test_fetch_not_found_and_errors_return_none():
    empty = mock_client(lambda req: httpx.Response(200, json=[]))
    assert pchome.fetch(A, client=empty, sleep=lambda s: None) is None

    calls = []

    def flaky(req):
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectError("boom")
        return httpx.Response(404, text="<html>404</html>")
    assert pchome.fetch(A, client=mock_client(flaky), sleep=lambda s: None) is None
    assert len(calls) == pchome.ATTEMPTS


def test_url_and_callback_patterns():
    assert pchome.URL_RE.search(f"看這個 https://24h.pchome.com.tw/prod/{A}?fq=/S").group(1) == A
    app = bot.build("123:abc", Store(":memory:"))
    patterns = [h.pattern.pattern for g in app.handlers.values() for h in g
                if hasattr(h, "pattern") and h.pattern is not None]
    for data in [f"add_{A}", f"list_1_{A}", f"del_1_{A}", f"undo_{A}", "No", "Yes"]:
        assert any(re.match(p, data) for p in patterns), data


def test_next_check_is_minute_one():
    t = dt.datetime(2026, 10, 7, 9, 30, tzinfo=dt.UTC)
    assert bot.next_check(t) == dt.datetime(2026, 10, 7, 10, 1, tzinfo=dt.UTC)
    t = dt.datetime(2026, 10, 7, 9, 0, 30, tzinfo=dt.UTC)
    assert bot.next_check(t) == dt.datetime(2026, 10, 7, 9, 1, tzinfo=dt.UTC)
