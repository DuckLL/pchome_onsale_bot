"""PChome 降價通知 Telegram bot.

Paste a https://24h.pchome.com.tw/prod/... URL to watch a product; /list and
/delete manage the watch list. Every hour (at minute 1) each watched product
is checked once and its watchers are told when the price dropped. A product
PChome stops returning for more than MAX_ERRORS checks in a row is dropped
from every list.

    python bot.py            run the bot (BOT_TOKEN, DB_PATH from the environment)
    python bot.py --check    fetch every watched price and print what would be
                             sent; writes nothing and talks to no one
"""

import argparse
import asyncio
import datetime as dt
import html
import logging
import os
import sys
from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import pchome
from store import Store

log = logging.getLogger("pchome_bot")

MAX_ERRORS = 24
CHECK_MINUTE = 1


@dataclass(frozen=True)
class Notice:
    users: list[int]
    html: str
    text: str


def _link(pid: str, body: str) -> str:
    return f'<a href="{pchome.prod_url(pid)}">{html.escape(body)}</a>'


async def check_prices(store: Store, fetch=pchome.fetch, *, write: bool = True) -> list[Notice]:
    """Check every watched product once; return the messages to send.

    Fetching is blocking (a pause before every request), so it runs in a
    thread; the database is only touched from the calling thread.
    """
    notices = []
    for pid in store.watched_pids():
        prod = store.product(pid)
        new = await asyncio.to_thread(fetch, pid)
        if new is None:
            errors = prod["error"] if prod and prod["error"] else 0
            if errors > MAX_ERRORS:
                name = prod["name"] if prod else pid
                body = f"{name}\n此商品已下架，自動移除監控"
                notices.append(Notice(store.watchers(pid), _link(pid, body),
                                      f"{body}\n{pchome.prod_url(pid)}"))
                if write:
                    store.remove_product(pid)
            elif write:
                store.record_error(pid)
            continue
        if prod and new.price < prod["last_price"]:
            body = f"{prod['name']}\n{prod['last_price']} -> {new.price}"
            notices.append(Notice(store.watchers(pid), _link(pid, body),
                                  f"{body}\n{pchome.prod_url(pid)}"))
        if write:
            store.record_price(pid, new.price, new.name)
    return notices


async def send(bot, notice: Notice) -> None:
    """Deliver to each watcher; one failing chat never stops the others."""
    for user in notice.users:
        try:
            try:
                await bot.send_message(user, notice.html, parse_mode=ParseMode.HTML,
                                       disable_web_page_preview=True)
            except BadRequest as e:
                log.warning("send %s: %s; retrying as plain text", user, e)
                await bot.send_message(user, notice.text, disable_web_page_preview=True)
        except Forbidden as e:
            log.warning("send %s: %s (user blocked the bot?)", user, e)
        except TelegramError as e:
            log.error("send %s: %s", user, e)


async def hourly(context: ContextTypes.DEFAULT_TYPE) -> None:
    store: Store = context.bot_data["store"]
    notices = await check_prices(store)
    log.info("checked %d product(s), %d notice(s)", len(store.watched_pids()), len(notices))
    for notice in notices:
        await send(context.bot, notice)


# --- chat handlers -------------------------------------------------------
# callback_data formats are the 2022 bot's ("list_{user}_{pid}", "del_...",
# "undo_{pid}", "No") so buttons already sitting in chats keep working. The
# user id inside them is ignored; the person pressing is who we act for.


def _user(update: Update) -> int:
    return update.effective_user.id


async def on_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pid = pchome.URL_RE.search(update.message.text).group(1)
    prod = await asyncio.to_thread(pchome.fetch, pid)
    if prod is None:
        await update.message.reply_text("查無此商品")
        return
    await update.message.reply_text(prod.name, reply_markup=InlineKeyboardMarkup([[
        InlineKeyboardButton("Yes", callback_data=f"add_{pid}"),
        InlineKeyboardButton("No", callback_data="No"),
    ]]))


async def on_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await _watch(query, context.bot_data["store"], _user(update), query.data.split("_", 1)[1])


async def on_undo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await _watch(query, context.bot_data["store"], _user(update), query.data.split("_", 1)[1])


async def _watch(query, store: Store, user: int, pid: str) -> None:
    prod = await asyncio.to_thread(pchome.fetch, pid)
    if prod is None:
        await query.edit_message_text("此商品已下架")
        return
    store.watch(user, pid, prod.name, prod.price)
    await query.edit_message_text(f"目前價錢: {prod.price}")


async def on_cancel_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("動作取消")


async def on_stale_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # A "Yes" button from before 2026-10-07 carried no product id.
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("請重新貼上商品網址")


async def on_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _menu(update, context, "目前監控商品", "list")


async def on_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _menu(update, context, "點選刪除", "del")


async def _menu(update: Update, context, title: str, action: str) -> None:
    user = _user(update)
    items = context.bot_data["store"].items(user)
    if not items:
        await update.message.reply_text("目前沒有監控商品，貼上 PChome 商品網址就能新增")
        return
    await update.message.reply_text(title, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton(row["name"], callback_data=f"{action}_{user}_{row['pid']}")]
        for row in items
    ]))


async def on_list_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    store: Store = context.bot_data["store"]
    pid = query.data.rsplit("_", 1)[1]
    item, prod = store.item(_user(update), pid), store.product(pid)
    if item is None or prod is None:
        await query.edit_message_text("此商品已不存在監控名單中")
        return
    await query.edit_message_text(
        _link(pid, f"商品資訊: {item['name']}\n目前價錢: {prod['last_price']}"),
        parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def on_delete_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    store: Store = context.bot_data["store"]
    user, pid = _user(update), query.data.rsplit("_", 1)[1]
    item = store.item(user, pid)
    if item is None:
        await query.edit_message_text("此商品已不存在監控名單中")
        return
    store.unwatch(user, pid)
    await query.edit_message_text(
        _link(pid, f"刪除商品: {item['name']}"), parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("反悔", callback_data=f"undo_{pid}")]]))


async def on_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("動作取消")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("handler failed", exc_info=context.error)


def next_check(now: dt.datetime) -> dt.datetime:
    at = now.replace(minute=CHECK_MINUTE, second=0, microsecond=0)
    return at if at > now else at + dt.timedelta(hours=1)


def build(token: str, store: Store) -> Application:
    app = Application.builder().token(token).build()
    app.bot_data["store"] = store
    app.add_handler(MessageHandler(filters.Regex(pchome.URL_RE), on_url))
    app.add_handler(CommandHandler("list", on_list))
    app.add_handler(CommandHandler("delete", on_delete))
    app.add_handler(CommandHandler("cancel", on_cancel_command))
    app.add_handler(CallbackQueryHandler(on_add, pattern=f"^add_{pchome.PID_RE.pattern}$"))
    app.add_handler(CallbackQueryHandler(on_list_item, pattern="^list_"))
    app.add_handler(CallbackQueryHandler(on_delete_item, pattern="^del_"))
    app.add_handler(CallbackQueryHandler(on_undo, pattern=f"^undo_{pchome.PID_RE.pattern}$"))
    app.add_handler(CallbackQueryHandler(on_cancel_button, pattern="^No$"))
    app.add_handler(CallbackQueryHandler(on_stale_yes, pattern="^Yes$"))
    app.add_error_handler(on_error)
    app.job_queue.run_repeating(hourly, interval=3600,
                                first=next_check(dt.datetime.now(dt.UTC)))
    return app


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="print what the hourly check would send; change nothing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    store = Store(os.environ.get("DB_PATH", "/data/bot.db"))
    if args.check:
        notices = asyncio.run(check_prices(store, write=False))
        print(f"{len(store.watched_pids())} product(s) watched, {len(notices)} notice(s)")
        for n in notices:
            print(f"-> {n.users}: {n.text!r}")
        return 0

    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("BOT_TOKEN is not set", file=sys.stderr)
        return 2
    build(token, store).run_polling()
    return 0


if __name__ == "__main__":
    sys.exit(main())
