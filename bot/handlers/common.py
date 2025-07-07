from django.utils import timezone
from bot.bot_instance import bot
from bot.keyboards import main_markup
from telebot.types import Message, CallbackQuery
from django.conf import settings
from bot.texts import START_TEXT, PAY_TEXT, STATUS_ACTIVE, STATUS_INACTIVE, THANKS_PAYMENT
import requests
import json

# Реальный запрос к API Точка

def generate_payment_url(user):
    url = "https://api.tochka.com/api/v1/invoice/create"
    headers = {
        "Authorization": f"Bearer {settings.TOCHKA_API_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "accountId": settings.TOCHKA_ACCOUNT_ID,
        "amount": 1,  # сумма в копейках (пример: 1000 = 10 рублей)
        "currency": "RUB",
        "description": f"Подписка для пользователя {user.telegram_id}",
        "externalId": str(user.telegram_id),
        "successUrl": "https://t.me/your_bot",  # куда редиректить после оплаты
        "failUrl": "https://t.me/your_bot"
    }
    try:
        response = requests.post(url, headers=headers, data=json.dumps(data), timeout=10)
        response.raise_for_status()
        resp_json = response.json()
        return resp_json.get("paymentUrl", "Ошибка генерации ссылки оплаты")
    except Exception as e:
        return f"Ошибка оплаты: {e}"

def start(message: Message) -> None:
    from bot.models import User
    user_id = message.from_user.id
    user, created = User.objects.get_or_create(
        telegram_id=user_id,
        defaults={
            'user_tg_name': message.from_user.username,
            'user_name': message.from_user.first_name,
        }
    )
    now = timezone.now()
    if user.subscription_end and user.subscription_end > now:
        days_left = (user.subscription_end - now).days
        bot.send_message(user_id, STATUS_ACTIVE.format(date=user.subscription_end.strftime('%d.%m.%Y'), days=days_left), reply_markup=main_markup)
    else:
        bot.send_message(user_id, START_TEXT, reply_markup=main_markup)

def pay_subscription(call: CallbackQuery) -> None:
    from bot.models import User
    user = User.objects.get(telegram_id=call.from_user.id)
    payment_url = generate_payment_url(user)
    bot.send_message(call.message.chat.id, f"{PAY_TEXT}\n{payment_url}")

def check_subscription(call: CallbackQuery) -> None:
    from bot.models import User
    user = User.objects.get(telegram_id=call.from_user.id)
    now = timezone.now()
    if user.subscription_end and user.subscription_end > now:
        days_left = (user.subscription_end - now).days
        bot.send_message(call.message.chat.id, STATUS_ACTIVE.format(date=user.subscription_end.strftime('%d.%m.%Y'), days=days_left))
    else:
        bot.send_message(call.message.chat.id, STATUS_INACTIVE)

def after_payment(user_id):
    bot.send_message(user_id, THANKS_PAYMENT.format(invite_link=settings.INVITE_LINK))

    

