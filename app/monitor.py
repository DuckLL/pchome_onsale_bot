from utils import *
from config import BOT_TOKEN
from telegram import ParseMode
from telegram.ext import Updater

updater = Updater(BOT_TOKEN)


def broadcast(pid, text):
    for monitor_row in monitor_db.find(pid=pid):
        updater.bot.sendMessage(monitor_row["user"],
                                text,
                                parse_mode=ParseMode.MARKDOWN,
                                disable_web_page_preview=True)


def main():
    for monitor_row in monitor_db.distinct("pid"):
        pid = monitor_row["pid"]
        prod = prod_db.find_one(pid=pid)
        new_prod = get_prod_info(pid)
        if new_prod == None:
            error = prod["error"]
            if error > 24:
                broadcast(
                    pid,
                    f"[{prod['name']}\n此商品以下架，自動移除監控](https://24h.pchome.com.tw/prod/{pid})"
                )
                monitor_db.delete(pid=pid)
                prod_db.delete(pid=pid)
            else:
                prod_db.update(dict(pid=pid, error=error + 1), ["pid"])
        else:
            last_price = prod["last_price"]
            new_price = new_prod["Price"]["P"]
            if new_price < last_price:
                broadcast(
                    pid,
                    f"[{prod['name']}\n{last_price} -> {new_price}](https://24h.pchome.com.tw/prod/{pid})"
                )
            prod_db.update(dict(pid=pid, last_price=new_price, error=0),
                           ["pid"])


if __name__ == '__main__':
    main()