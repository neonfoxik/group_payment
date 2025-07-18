from django.core.management.base import BaseCommand
from bot.models import User
from django.utils import timezone
from bot import bot
from datetime import timedelta
import logging
from django.conf import settings

logger = logging.getLogger("ban_expired")

class Command(BaseCommand):
    help = 'Удаляет пользователей с истекшей подпиской из группы.'

    def handle(self, *args, **kwargs):
        now = timezone.now()
        group_id = settings.GROUP_ID
        users = User.objects.filter(subscription_end__lt=now, is_subscribed=True)
        for user in users:
            try:
                bot.kick_chat_member(group_id, user.telegram_id)
                logger.info(f"Пользователь {user.telegram_id} кикнут из группы.")
            except Exception as e:
                logger.error(f"Не удалось кикнуть {user.telegram_id}: {e}")
            user.is_subscribed = False
            user.save() 