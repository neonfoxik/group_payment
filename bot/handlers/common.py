from django.utils import timezone
from bot.bot_instance import bot
from bot.keyboards import main_markup, main_inline_markup
from telebot.types import Message, CallbackQuery
from django.conf import settings
from bot.texts import START_TEXT, STATUS_ACTIVE, STATUS_INACTIVE, THANKS_PAYMENT
import requests
import json
import uuid
from bot.models import User, PromoCode
import logging
logger = logging.getLogger("tochka_payment")
import re
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

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
    from django.utils import timezone
    now = timezone.now()
    if user.is_subscribed and user.subscription_end:
        days = (user.subscription_end - now).days
        return True, user.subscription_end.strftime('%d.%m.%Y'), max(days, 0)
    return False, None, None

def get_status_text(user):
    is_active, date, days = get_subscription_status(user)
    if is_active:
        return STATUS_ACTIVE.format(date=date, days=days)
    else:
        return STATUS_INACTIVE

# Универсальная функция для генерации и показа главного экрана

def show_main_screen(user, chat_id, edit_message_id=None):
    from bot.texts import START_TEXT
    from django.utils import timezone
    is_active, date, days = get_subscription_status(user)
    if is_active:
        status_text = STATUS_ACTIVE.format(date=date, days=days)
        button_text = "Продлить подписку"
        purpose = "Продление подписки"
    else:
        status_text = STATUS_INACTIVE
        button_text = "Оплатить подписку"
        purpose = "Оплата подписки"
    payment_link, operation_id, error = create_tochka_payment_link_with_receipt(user.telegram_id, 1, purpose, user.email)
    if operation_id:
        if not user.operation_ids:
            user.operation_ids = []
        user.operation_ids.append(operation_id)
        user.save()
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Статус подписки", callback_data="check_subscription"))
    if payment_link:
        markup.add(InlineKeyboardButton(button_text, url=payment_link))
    markup.add(InlineKeyboardButton("Проверить оплату", callback_data="check_payment"))
    markup.add(InlineKeyboardButton("Проверить промокод", callback_data="check_promo"))
    if edit_message_id:
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=edit_message_id,
                text=f"{START_TEXT}\n\n{status_text}",
                reply_markup=markup
            )
        except Exception:
            pass
    else:
        bot.send_message(
            chat_id,
            f"{START_TEXT}\n\n{status_text}",
            reply_markup=markup
        )

# Обработчик для возврата на главное меню по callback
@bot.callback_query_handler(func=lambda call: call.data == "main_menu")
def main_menu_callback(call: CallbackQuery):
    from bot.models import User
    user, _ = User.objects.get_or_create(telegram_id=str(call.from_user.id))
    show_main_screen(user, call.from_user.id, edit_message_id=call.message.message_id)
    bot.answer_callback_query(call.id)

# Обработчик для кнопки 'Статус подписки'
@bot.callback_query_handler(func=lambda call: call.data == "check_subscription")
def check_subscription_callback(call: CallbackQuery):
    from bot.models import User
    user, _ = User.objects.get_or_create(telegram_id=str(call.from_user.id))
    is_active, date, days = get_subscription_status(user)
    if is_active:
        text = STATUS_ACTIVE.format(date=date, days=days)
    else:
        text = STATUS_INACTIVE
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Назад", callback_data="main_menu"))
    try:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=text,
            reply_markup=markup
        )
    except Exception:
        pass
    bot.answer_callback_query(call.id)

# Использовать show_main_screen в start_registration и save_email

def start_registration(message: Message):
    user, created = register_user(message)
    from bot.models import User
    from django.utils import timezone
    if not user.email:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Отмена", callback_data="cancel_email"))
        bot.send_message(message.from_user.id, "Пожалуйста, введите ваш email для получения чека:", reply_markup=markup)
        bot.register_next_step_handler(message, save_email)
        return
    show_main_screen(user, message.from_user.id)

def save_email(message: Message):
    if message.text and message.text.lower() == 'отмена':
        bot.send_message(message.from_user.id, "Изменение email отменено.")
        return
    email = message.text.strip()
    if not re.match(EMAIL_REGEX, email):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Отмена", callback_data="cancel_email"))
        bot.send_message(message.from_user.id, "Некорректный email. Попробуйте ещё раз или отправьте /email.", reply_markup=markup)
        return
    from bot.models import User
    from django.utils import timezone
    user, _ = User.objects.get_or_create(telegram_id=str(message.from_user.id))
    user.email = email
    user.save()
    bot.send_message(message.from_user.id, f"Ваш email сохранён: {email}")
    show_main_screen(user, message.from_user.id)

EMAIL_REGEX = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"

@bot.message_handler(commands=['email'])
def ask_email(message: Message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Отмена", callback_data="cancel_email"))
    bot.send_message(message.from_user.id, "Пожалуйста, введите ваш email для получения чека:", reply_markup=markup)
    bot.register_next_step_handler(message, save_email)

def activate_promo(message: Message):
    code = message.text.strip()
    promo = PromoCode.objects.filter(code=code, is_used=False).first()
    if not promo:
        bot.send_message(message.from_user.id, "Промокод не найден или уже использован.")
        return
    user, _ = User.objects.get_or_create(telegram_id=str(message.from_user.id))
    from django.utils import timezone
    now = timezone.now()
    # Если подписка просрочена, новая дата = сегодня + 30 дней
    if user.subscription_end and user.subscription_end > now:
        user.subscription_end = user.subscription_end + timezone.timedelta(days=30)
    else:
        user.subscription_end = now + timezone.timedelta(days=30)
    user.is_subscribed = True
    user.save()
    promo.is_used = True
    promo.used_by = user
    promo.save()
    bot.send_message(message.from_user.id, "Промокод активирован! Вам выдан бесплатный доступ на 30 дней.")
    show_main_screen(user, message.from_user.id)

@bot.callback_query_handler(func=lambda call: call.data == "check_promo")
def check_promo_callback(call: CallbackQuery):
    bot.send_message(call.from_user.id, "Введите промокод:")
    bot.register_next_step_handler(call.message, activate_promo) 