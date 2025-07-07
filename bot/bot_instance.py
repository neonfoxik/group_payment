from django.conf import settings
import telebot

commands = settings.BOT_COMMANDS

bot = telebot.TeleBot(
    settings.BOT_TOKEN,
    threaded=False,
    skip_pending=True,
)

bot.set_my_commands(commands) 