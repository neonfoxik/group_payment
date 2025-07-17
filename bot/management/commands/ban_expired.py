from django.core.management.base import BaseCommand
from bot.models import User
from django.utils import timezone
from bot import bot
from datetime import timedelta
import logging

# Укажите ID вашей группы
GROUP_ID = -4709622920 
logger = logging.getLogger("ban_expired")

class Command(BaseCommand):
    help = 'Удаляет пользователей с истекшей подпиской из группы.'

    def handle(self, *args, **kwargs):
        now = timezone.now()
        users = User.objects.filter(subscription_end__lt<=now, is_subscribed=True)
        for user in users:
            try:
                bot.ban_chat_member(GROUP_ID, user.telegram_id)
                logger.info(f"Пользователь {user.telegram_id} забанен в группе.")
            except Exception as e:
                logger.warning(f"Не удалось забанить {user.telegram_id}: {e}. Пробую кикнуть.")
                try:
                    bot.kick_chat_member(GROUP_ID, user.telegram_id)
                    logger.info(f"Пользователь {user.telegram_id} кикнут из группы.")
                except Exception as e2:
                    logger.error(f"Не удалось кикнуть {user.telegram_id}: {e2}")
            user.is_subscribed = False
            user.save() 