from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)


main_markup = InlineKeyboardMarkup()
btn1 = InlineKeyboardButton("Статус подписки", callback_data="check_subscription")
btn2 = InlineKeyboardButton("Оплатить подписку", callback_data="pay_subscription")
main_markup.add(btn1).add(btn2)

check_subscription = InlineKeyboardMarkup()
btn1 = InlineKeyboardButton("Проверить подписку", callback_data="check_subscription")
check_subscription.add(btn1)


coins_markup = InlineKeyboardMarkup()
btn1 = InlineKeyboardButton("🚜Ферма монет🚜", callback_data="coins_farm")
btn2 = InlineKeyboardButton("🔄Обмен монет🔄", callback_data="coins_trade")
btn3 = InlineKeyboardButton("Евенты", callback_data="events_menu")
btn4 = InlineKeyboardButton("Назад🔙", callback_data="main_menu")
coins_markup.add(btn1, btn2).add(btn3, btn4)

referal_markup = InlineKeyboardMarkup()
btn1 = InlineKeyboardButton("🔰Получить реферальную ссылку🔰", callback_data="get_referal_link")
btn2 = InlineKeyboardButton("Назад🔙", callback_data="main_menu")
referal_markup.add(btn1).add(btn2)

UNIVERSAL_BUTTONS = InlineKeyboardMarkup()
btn1 = InlineKeyboardButton("Назад👈", callback_data="main_menu")
UNIVERSAL_BUTTONS.add(btn1)

UNIVERSAL_VIDEO_MARKUP = InlineKeyboardMarkup()
btn1 = InlineKeyboardButton("Назад👈", callback_data="main_video_menu")
UNIVERSAL_VIDEO_MARKUP.add(btn1)

ADMIN_MARKUP = InlineKeyboardMarkup()
btn1 = InlineKeyboardButton("Рассылка", callback_data="newsletter")
ADMIN_MARKUP.add(btn1)


def main_inline_markup():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Оплатить подписку", callback_data="pay_subscription"))
    markup.add(InlineKeyboardButton("Проверить оплату", callback_data="check_payment"))
    return markup
