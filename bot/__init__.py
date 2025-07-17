# Этот файл нужен для корректной работы пакета bot
from .bot_instance import bot


import logging
import telebot
from django.conf import settings

commands = settings.BOT_COMMANDS

logger = telebot.logger
logger.setLevel(logging.INFO)
logging.basicConfig(level=logging.INFO, filename="ai_log.log", filemode="w")

logging.info(f'@{bot.get_me().username} started')

# Импорт management.commands для кастомных команд
try:
    import bot.management.commands
except ImportError:
    pass