# Этот файл нужен для корректной работы пакета bot
from .bot_instance import bot
from bot.handlers.common import start, pay_subscription, check_subscription, after_payment

import logging
import telebot
from django.conf import settings

commands = settings.BOT_COMMANDS

logger = telebot.logger
logger.setLevel(logging.INFO)
logging.basicConfig(level=logging.INFO, filename="ai_log.log", filemode="w")

logging.info(f'@{bot.get_me().username} started')

# Регистрируем обработчики
bot.message_handler(commands=["start"])(start)
bot.callback_query_handler(lambda c: c.data == "pay_subscription")(pay_subscription)
bot.callback_query_handler(lambda c: c.data == "check_subscription")(check_subscription)

# Импорт management.commands для кастомных команд
try:
    import bot.management.commands
except ImportError:
    pass