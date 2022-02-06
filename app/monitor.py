from utils import *
from config import BOT_TOKEN
from telegram import ParseMode
from telegram.ext import Updater

updater = Updater(BOT_TOKEN)

for monitor_row in monitor_db.distinct("pid"):
    pid = monitor_row["pid"]
    prod = prod_db.find_one(pid=pid)
    last_price = prod["last_price"]
    new_prod = get_prod_info(pid)
    if new_prod == None:
        for monitor_row in monitor_db.find(pid=pid):
            text = f"[{prod['name']}\n此商品以下架，自動移除監控](https://24h.pchome.com.tw/prod/{pid})"
            updater.bot.sendMessage(monitor_row["user"],text,parse_mode=ParseMode.MARKDOWN,disable_web_page_preview=True)
        monitor_db.delete(pid=pid)
        prod_db.delete(pid=pid)
    else:
        new_price = new_prod["Price"]["P"]
        if new_price < last_price:
            for monitor_row in monitor_db.find(pid=pid):
                text = f"[{prod['name']}\n{last_price} -> {new_price}](https://24h.pchome.com.tw/prod/{pid})"
                updater.bot.sendMessage(monitor_row["user"],text,parse_mode=ParseMode.MARKDOWN,disable_web_page_preview=True)
        prod_db.update({"pid":pid,"last_price":new_price},["pid"])