import re
from config import BOT_TOKEN
from utils import *

from telegram import Update, ParseMode, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, ConversationHandler, CallbackQueryHandler


def cancel(update: Update, _: CallbackContext) -> int:
    update.callback_query.edit_message_text("動作取消")
    return ConversationHandler.END


def add(update: Update, context: CallbackContext):
    match = re.search(r"([A-Z0-9]{6}-[A-Z0-9]{9})", update.message.text)
    if match:
        pid = match.groups(1)[0]
    context.user_data["pid"] = pid
    prod = get_prod_info(pid)
    if prod == None:
        update.message.reply_text(text="查無此商品")
        return ConversationHandler.END
    update.message.reply_text(text=prod["Name"],
                              parse_mode=ParseMode.MARKDOWN,
                              reply_markup=InlineKeyboardMarkup([
                                  [yes_button, no_button],
                              ]))
    return 0


def confirm(update: Update, context: CallbackContext) -> int:
    add_monitor(update.callback_query.from_user["id"],
                context.user_data["pid"])
    price = get_prod_info(context.user_data["pid"])["Price"]["P"]
    update.callback_query.edit_message_text(f"目前價錢: {price}")
    return ConversationHandler.END


yes_button = InlineKeyboardButton("Yes", callback_data="Yes")
no_button = InlineKeyboardButton("No", callback_data="No")

add_conv = ConversationHandler(
    entry_points=[
        MessageHandler(
            Filters.regex(
                'https://24h\.pchome\.com\.tw/prod/[A-Z0-9]{6}-[A-Z0-9]{9}'),
            add)
    ],
    states={
        0: [
            CallbackQueryHandler(confirm, pattern="Yes"),
            CallbackQueryHandler(cancel, pattern="No")
        ],
    },
    fallbacks=[CommandHandler('cancel', cancel)],
)


def list_item(update: Update, context: CallbackContext) -> None:
    buttons = []
    for monitor_row in monitor_db.find(user=update.message.from_user["id"]):
        buttons.append([
            InlineKeyboardButton(
                monitor_row["name"],
                callback_data=f"list_{monitor_row['user']}_{monitor_row['pid']}"
            )
        ])
    update.message.reply_text(text="目前監控商品",
                              reply_markup=InlineKeyboardMarkup(buttons))
    return


def list_confirm(update: Update, context: CallbackContext) -> None:
    item = update.callback_query.data.split("_")
    monitor_row = monitor_db.find_one(user=item[1], pid=item[2])
    if monitor_row == None:
        update.callback_query.edit_message_text("此商品已不存在監控名單中")
        return
    prod_row = prod_db.find_one(pid=item[2])
    if prod_row == None:
        update.callback_query.edit_message_text("此商品已不存在監控名單中")
        return
    update.callback_query.edit_message_text(
        f"[商品資訊: {monitor_row['name']}\n目前價錢: {prod_row['last_price']}](https://24h.pchome.com.tw/prod/{monitor_row['pid']})",
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True)
    return


def delete(update: Update, context: CallbackContext) -> None:
    buttons = []
    for monitor_row in monitor_db.find(user=update.message.from_user["id"]):
        buttons.append([
            InlineKeyboardButton(
                monitor_row["name"],
                callback_data=f"del_{monitor_row['user']}_{monitor_row['pid']}"
            )
        ])
    update.message.reply_text(text="點選刪除",
                              parse_mode=ParseMode.MARKDOWN,
                              reply_markup=InlineKeyboardMarkup(buttons))
    return


def delete_confirm(update: Update, context: CallbackContext) -> None:
    item = update.callback_query.data.split("_")
    monitor_row = monitor_db.find_one(user=item[1], pid=item[2])
    if monitor_row == None:
        update.callback_query.edit_message_text("此商品已不存在監控名單中")
        return
    delete_monitor(monitor_row["user"], monitor_row["pid"])
    update.callback_query.edit_message_text(
        f"[刪除商品: {monitor_row['name']}](https://24h.pchome.com.tw/prod/{monitor_row['pid']})",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("反悔",
                                 callback_data=f"undo_{monitor_row['pid']}")
        ]]),
        disable_web_page_preview=True)
    return


def undo(update: Update, context: CallbackContext) -> None:
    pid = update.callback_query.data.split("_")[1]
    prod = get_prod_info(pid)
    if prod == None:
        update.callback_query.edit_message_text(text="查商品以下架")
        return
    add_monitor(update.callback_query.from_user["id"], pid)
    price = get_prod_info(pid)["Price"]["P"]
    update.callback_query.edit_message_text(f"目前價錢: {price}")
    return


def main():
    updater = Updater(BOT_TOKEN)
    updater.dispatcher.add_handler(add_conv)
    updater.dispatcher.add_handler(CommandHandler('list', list_item))
    updater.dispatcher.add_handler(CommandHandler('delete', delete))
    updater.dispatcher.add_handler(CommandHandler('cancel', cancel))
    updater.dispatcher.add_handler(
        CallbackQueryHandler(delete_confirm, pattern="del_"))
    updater.dispatcher.add_handler(
        CallbackQueryHandler(list_confirm, pattern="list_"))
    updater.dispatcher.add_handler(CallbackQueryHandler(undo, pattern="undo_"))
    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()