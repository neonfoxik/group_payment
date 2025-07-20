from functools import wraps

from django.conf import settings
from telebot.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from bot.keyboards import ADMIN_MARKUP
from bot.bot_instance import bot
from bot import logger
from bot.models import User, PromoCode
import random
import string

def admin_permission(func):
    """
    Checking user for admin permission to access the function.
    """

    @wraps(func)
    def wrapped(message: Message) -> None:
        user_id = message.from_user.id
        user = User.objects.get(telegram_id=user_id)
        if not user.is_admin:
            bot.send_message(user_id, '⛔ У вас нет администраторского доступа')
            logger.warning(f'Попытка доступа к админ панели от {user_id}')
            return
        return func(message)

    return wrapped


@admin_permission
def admin_menu(msg: Message):
    bot.send_message(msg.from_user.id, 'Админ панель', reply_markup=ADMIN_MARKUP)

@admin_permission
def newsletter(call: CallbackQuery):
    bot.send_message(call.from_user.id, 'Пожалуйста, отправьте текст для рассылки.')
    bot.register_next_step_handler(call.message, handle_message)


@admin_permission
def handle_message(msg: Message):
    users = User.objects.all()  # Получаем всех пользователей

    for user in users:
        try:
            if msg.forward_from or msg.forward_from_chat:
                bot.forward_message(user.telegram_id, msg.chat.id, msg.message_id)
            else:
                if msg.content_type == 'text':
                    bot.send_message(user.telegram_id, msg.text)
                elif msg.content_type == 'video':
                    bot.send_video(user.telegram_id, msg.video.file_id)
                elif msg.content_type == 'sticker':
                    bot.send_sticker(user.telegram_id, msg.sticker.file_id)
                elif msg.content_type == 'document':
                    bot.send_document(user.telegram_id, msg.document.file_id)
                elif msg.content_type == 'photo':
                    bot.send_photo(user.telegram_id, msg.photo[-1].file_id)
                elif msg.content_type == 'audio':
                    bot.send_audio(user.telegram_id, msg.audio.file_id)
                elif msg.content_type == 'voice':
                    bot.send_voice(user.telegram_id, msg.voice.file_id)
                else:
                    logger.warning(f"Неизвестный тип сообщения: {msg.content_type}")

        except Exception as e:
            logger.warning(f'Пользователь {user.telegram_id} заблокировал бота или произошла другая ошибка: {e}')
    bot.send_message(msg.from_user.id, '✅ Сообщение успешно отправлено всем пользователям.')


@bot.message_handler(commands=['gen'])
def generate_promocode(message: Message):
    if message.from_user.id != settings.OWNER_ID:
        bot.send_message(message.from_user.id, '⛔ Только владелец может генерировать промокоды.')
        return
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
    PromoCode.objects.create(code=code)
    bot.send_message(message.from_user.id, f'Промокод: {code}')