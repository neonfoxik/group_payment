from django.core.management.base import BaseCommand
from bot.models import User
from django.utils import timezone
from bot import bot
from bot.texts import REMINDER_TEXT
from datetime import timedelta

class Command(BaseCommand):
    help = 'Отправляет напоминания о продлении подписки за 5 дней до окончания.'

    def handle(self, *args, **kwargs):
        now = timezone.now()
        remind_date = now + timedelta(days=5)
        users = User.objects.filter(subscription_end__date=remind_date.date(), is_subscribed=True)
        for user in users:
            bot.send_message(user.telegram_id, REMINDER_TEXT) 