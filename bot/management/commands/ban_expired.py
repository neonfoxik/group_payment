from django.core.management.base import BaseCommand
from bot.models import User
from django.utils import timezone
from bot import bot
from datetime import timedelta

# Укажите ID вашей группы
GROUP_ID = -1001234567890  # замените на свой

class Command(BaseCommand):
    help = 'Удаляет пользователей с истекшей подпиской из группы.'

    def handle(self, *args, **kwargs):
        now = timezone.now()
        users = User.objects.filter(subscription_end__lt=now, is_subscribed=True)
        for user in users:
            try:
                bot.ban_chat_member(GROUP_ID, user.telegram_id)
            except Exception:
                pass
            user.is_subscribed = False
            user.save() 