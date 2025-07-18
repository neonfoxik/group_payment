from django.utils import timezone
from bot.bot_instance import bot
from bot.keyboards import main_markup, main_inline_markup
from telebot.types import Message, CallbackQuery
from django.conf import settings
from bot.texts import START_TEXT, PAY_TEXT, STATUS_ACTIVE, STATUS_INACTIVE, THANKS_PAYMENT
import requests
import json
import uuid
from bot.models import User
import logging
logger = logging.getLogger("tochka_payment")
import re

# Реальный запрос к API Точка


def get_merchant_id():
    """Получить merchantId через API Точки по customerCode из settings."""
    from django.conf import settings
    url = f"https://enter.tochka.com/uapi/acquiring/v1.0/retailers?customerCode={settings.TOCHKA_CUSTOMER_CODE}"
    headers = {
        "Authorization": f"Bearer {settings.TOCHKA_API_TOKEN}"
    }
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json().get("Data", {})
            retailers = data.get("Retailer", [])
            if retailers and isinstance(retailers, list):
                merchant_id = retailers[0].get("merchantId")
                if merchant_id:
                    return merchant_id, None
                else:
                    return None, "merchantId не найден в ответе API Точка"
            else:
                return None, "Retailer не найден в ответе API Точка"
        else:
            return None, f"Ошибка API Точка при получении merchantId: {response.status_code} {response.text}"
    except Exception as e:
        logger.exception("Ошибка при получении merchantId через API Точка")
        return None, f"Исключение: {str(e)}"


def create_tochka_payment_link_with_receipt(user_id, amount, purpose, email):
    from django.conf import settings
    merchant_id = settings.TOCHKA_MERCHANT_ID
    if not merchant_id:
        merchant_id, error = get_merchant_id()
        if not merchant_id:
            return None, None, f"Не удалось получить merchantId: {error}"
    url = "https://enter.tochka.com/uapi/acquiring/v1.0/payments_with_receipt"
    payload = {
        "Data": {
            "customerCode": settings.TOCHKA_CUSTOMER_CODE,
            "merchantId": merchant_id,
            "amount": amount,
            "purpose": purpose,
            "paymentMode": ["sbp", "card"],
            "redirectUrl": f"{settings.HOOK}/bot/tochka_payment_webhook/?user_id={user_id}",
            "Client": {
                "email": email
            },
            "Items": [
                {
                    "vatType": "none",
                    "name": "Подписка",
                    "amount": amount,
                    "quantity": 1,
                    "paymentMethod": "full_payment",
                    "paymentObject": "service",
                    "measure": "шт."
                }
            ]
        }
    }
    print("payload:", payload)  # Логируем payload для отладки
    headers = {
        "Authorization": f"Bearer {settings.TOCHKA_API_TOKEN}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        if response.status_code == 200:
            data = response.json().get("Data", {})
            return data.get("paymentLink"), data.get("operationId"), None
        else:
            logger.error(f"Ошибка API Точка: {response.status_code} {response.text}")
            return None, None, f"Ошибка API Точка: {response.status_code} {response.text}"
    except Exception as e:
        logger.exception("Ошибка при создании платёжной ссылки через API Точка")
        return None, None, f"Исключение: {str(e)}"


def send_invite_link(user_id):
    from django.conf import settings
    group_id = settings.GROUP_ID
    try:
        invite = bot.create_chat_invite_link(group_id, member_limit=1)
        invite_link = invite.invite_link
    except Exception as e:
        print(f'Ошибка при создании инвайт-ссылки: {e}')
        invite_link = None
    if invite_link:
        bot.send_message(user_id, f"Спасибо за оплату! Вот ваша ссылка для вступления: {invite_link}")
    else:
        bot.send_message(user_id, "Ошибка при создании ссылки для вступления. Обратитесь к администратору.")



def register_user(message):
    user_id = str(message.from_user.id)
    user, created = User.objects.get_or_create(
        telegram_id=user_id,
        defaults={
            'user_tg_name': message.from_user.username or 'none',
            'user_name': message.from_user.first_name or '',
        }
    )
    return user, created

def get_subscription_status(user):
    if user.is_subscribed and user.subscription_end:
        from django.utils import timezone
        days = (user.subscription_end - timezone.now()).days
        return True, user.subscription_end.strftime('%d.%m.%Y'), days
    return False, None, None

def get_payment_link_for_user(user_id, amount=1, purpose="Оплата подписки"):
    from bot.models import User
    user = User.objects.filter(telegram_id=str(user_id)).first()
    if not user or not user.email:
        return None, None, "Email пользователя не найден. Пожалуйста, укажите email через /email."
    return create_tochka_payment_link_with_receipt(user_id, amount, purpose, user.email)

def get_status_text(user):
    is_active, date, days = get_subscription_status(user)
    if is_active:
        return STATUS_ACTIVE.format(date=date, days=days)
    else:
        return STATUS_INACTIVE 

EMAIL_REGEX = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"

@bot.message_handler(commands=['email'])
def ask_email(message: Message):
    bot.send_message(message.from_user.id, "Пожалуйста, введите ваш email для получения чека:")
    bot.register_next_step_handler(message, save_email)

def save_email(message: Message):
    email = message.text.strip()
    if not re.match(EMAIL_REGEX, email):
        bot.send_message(message.from_user.id, "Некорректный email. Попробуйте ещё раз или отправьте /email.")
        return
    from bot.models import User
    user, _ = User.objects.get_or_create(telegram_id=str(message.from_user.id))
    user.email = email
    user.save()
    bot.send_message(message.from_user.id, f"Ваш email сохранён: {email}")

def start_registration(message: Message):
    user, created = register_user(message)
    bot.send_message(
        message.from_user.id,
        START_TEXT,
        reply_markup=main_inline_markup()
    )

start = bot.message_handler(commands=["start"])(start_registration)

def handle_pay(message: Message):
    user_id = message.from_user.id
    from bot.models import User
    user, _ = User.objects.get_or_create(telegram_id=str(user_id))
    if not user.email:
        bot.send_message(user_id, "Перед оплатой укажите ваш email с помощью команды /email")
        return
    amount = 1
    purpose = "Оплата подписки"
    payment_link, operation_id, error = create_tochka_payment_link_with_receipt(user_id, amount, purpose, user.email)
    if payment_link:
        if operation_id:
            if not user.operation_ids:
                user.operation_ids = []
            user.operation_ids.append(operation_id)
            user.save()
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Оплатить", url=payment_link))
        markup.add(InlineKeyboardButton("Проверить оплату", callback_data="check_payment"))
        bot.send_message(user_id, PAY_TEXT, reply_markup=markup)
    else:
        error_text = f"Ошибка при создании ссылки на оплату.\n{error if error else ''}"
        bot.send_message(user_id, error_text)

@bot.callback_query_handler(func=lambda call: call.data == "pay_subscription")
def pay_subscription_callback(call: CallbackQuery):
    handle_pay(call)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "check_payment")
def check_payment_callback(call: CallbackQuery):
    from bot.models import User
    from django.utils import timezone
    user = User.objects.filter(telegram_id=str(call.from_user.id)).first()
    if not user or not user.operation_ids:
        bot.answer_callback_query(call.id, "Нет данных для проверки оплаты.", show_alert=True)
        return
    approved_id = None
    for operation_id in list(user.operation_ids):  # копия списка для безопасного удаления
        api_url = f"https://enter.tochka.com/uapi/acquiring/v1.0/payments/{operation_id}"
        headers = {"Authorization": f"Bearer {settings.TOCHKA_API_TOKEN}"}
        resp = requests.get(api_url, headers=headers)
        if resp.status_code == 200:
            data = resp.json().get('Data', {})
            operation_list = data.get('Operation')
            if isinstance(operation_list, list) and operation_list:
                status = operation_list[0].get('status')
            else:
                status = data.get('status')
            if status == 'APPROVED':
                approved_id = operation_id
                break
    if approved_id:
        # Удаляем только подтверждённый operationId
        user.operation_ids = [oid for oid in user.operation_ids if oid != approved_id]
        now = timezone.now()
        if user.subscription_end and user.subscription_end > now:
            user.subscription_end = user.subscription_end + timezone.timedelta(days=30)
        else:
            user.subscription_end = now + timezone.timedelta(days=30)
        user.is_subscribed = True
        user.save()
        # Разбаниваем пользователя и отправляем ссылку
        try:
            from bot.management.commands.ban_expired import GROUP_ID
            bot.unban_chat_member(GROUP_ID, call.from_user.id)
        except Exception as e:
            print(f'Ошибка при разбане пользователя {call.from_user.id}: {e}')
        send_invite_link(call.from_user.id)
        bot.answer_callback_query(call.id, "Оплата подтверждена! Ссылка отправлена. Подписка активирована.", show_alert=True)
    else:
        bot.answer_callback_query(call.id, "Оплата не подтверждена по ни одному из платежей.", show_alert=True) 
