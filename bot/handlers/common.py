from django.utils import timezone
from bot.bot_instance import bot
from bot.keyboards import main_markup, main_inline_markup
from telebot.types import Message, CallbackQuery
from django.conf import settings
from bot.texts import START_TEXT, STATUS_ACTIVE, STATUS_INACTIVE, THANKS_PAYMENT, PAY_TEXT
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
    if user.operation_id:
        # Восстановить ссылку по старому operation_id
        payment_link = f"https://enter.tochka.com/uapi/acquiring/v1.0/payments_with_receipt/{user.operation_id}"
        return payment_link, user.operation_id, None
    payment_link, operation_id, error = create_tochka_payment_link_with_receipt(user_id, amount, purpose, user.email)
    if operation_id:
        user.operation_id = operation_id
        user.save()
    return payment_link, operation_id, error

def get_status_text(user):
    is_active, date, days = get_subscription_status(user)
    if is_active:
        return STATUS_ACTIVE.format(date=date, days=days)
    else:
        return STATUS_INACTIVE 

EMAIL_REGEX = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"

@bot.message_handler(commands=['email'])
def ask_email(message: Message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Отмена", callback_data="cancel_email"))
    bot.send_message(message.from_user.id, "Пожалуйста, введите ваш email для получения чека:", reply_markup=markup)
    bot.register_next_step_handler(message, save_email)

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
    # Проверяем статус подписки
    is_active = user.is_subscribed and user.subscription_end and user.subscription_end > timezone.now()
    if is_active:
        button_text = "Продлить подписку"
        purpose = "Продление подписки"
    else:
        button_text = "Оплатить"
        purpose = "Оплата подписки"
    payment_link, operation_id, error = create_tochka_payment_link_with_receipt(user.telegram_id, 1, purpose, user.email)
    if operation_id:
        user.operation_id = operation_id
        user.save()
    markup = InlineKeyboardMarkup()
    if payment_link:
        markup.add(InlineKeyboardButton(button_text, url=payment_link))
    markup.add(InlineKeyboardButton("Проверить оплату", callback_data="check_payment"))
    markup.add(InlineKeyboardButton("Ввести промокод", callback_data="check_promo"))
    markup.add(InlineKeyboardButton("Статус подписки", callback_data="check_status"))
    bot.send_message(message.from_user.id, START_TEXT, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "cancel_email")
def cancel_email_callback(call: CallbackQuery):
    bot.send_message(call.from_user.id, "Изменение email отменено.")
    bot.clear_step_handler_by_chat_id(call.from_user.id)
    bot.answer_callback_query(call.id)

def start_registration(message: Message):
    user, created = register_user(message)
    from bot.texts import START_TEXT
    from bot.models import User
    from django.utils import timezone
    if not user.email:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Отмена", callback_data="cancel_email"))
        bot.send_message(message.from_user.id, "Пожалуйста, введите ваш email для получения чека:", reply_markup=markup)
        bot.register_next_step_handler(message, save_email)
        return
    # Проверяем статус подписки
    is_active = user.is_subscribed and user.subscription_end and user.subscription_end > timezone.now()
    if is_active:
        button_text = "Продлить подписку"
        purpose = "Продление подписки"
    else:
        button_text = "Оплатить"
        purpose = "Оплата подписки"
    payment_link, operation_id, error = get_payment_link_for_user(user.telegram_id, 1, purpose)
    markup = InlineKeyboardMarkup()
    if payment_link:
        markup.add(InlineKeyboardButton(button_text, url=payment_link))
    markup.add(InlineKeyboardButton("Проверить оплату", callback_data="check_payment"))
    markup.add(InlineKeyboardButton("Ввести промокод", callback_data="check_promo"))
    markup.add(InlineKeyboardButton("Статус подписки", callback_data="check_status"))
    bot.send_message(
        message.from_user.id,
        START_TEXT,
        reply_markup=markup
    )

start = bot.message_handler(commands=["start"])(start_registration)

def handle_pay(message: Message, edit_message=False):
    user_id = message.from_user.id
    from bot.models import User
    user, _ = User.objects.get_or_create(telegram_id=str(user_id))
    if not user.email:
        if edit_message:
            try:
                bot.edit_message_text(
                    chat_id=message.message.chat.id,
                    message_id=message.message.message_id,
                    text="Перед оплатой укажите ваш email с помощью команды /email"
                )
            except Exception:
                pass
        else:
            bot.send_message(user_id, "Перед оплатой укажите ваш email с помощью команды /email")
        return
    amount = 1
    purpose = "Оплата подписки"
    payment_link, operation_id, error = create_tochka_payment_link_with_receipt(user_id, amount, purpose, user.email)
    if payment_link:
        if operation_id:
            user.operation_id = operation_id
            user.save()
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Оплатить", url=payment_link))
        markup.add(InlineKeyboardButton("Проверить оплату", callback_data="check_payment"))
        if edit_message:
            try:
                bot.edit_message_text(
                    chat_id=message.message.chat.id,
                    message_id=message.message.message_id,
                    text=PAY_TEXT,
                    reply_markup=markup
                )
            except Exception:
                pass
        else:
            bot.send_message(user_id, PAY_TEXT, reply_markup=markup)
    else:
        error_text = f"Ошибка при создании ссылки на оплату.\n{error if error else ''}"
        if edit_message:
            try:
                bot.edit_message_text(
                    chat_id=message.message.chat.id,
                    message_id=message.message.message_id,
                    text=error_text
                )
            except Exception:
                pass
        else:
            bot.send_message(user_id, error_text)

@bot.callback_query_handler(func=lambda call: call.data == "pay_subscription")
def pay_subscription_callback(call: CallbackQuery):
    # handle_pay теперь должен редактировать сообщение, а не отправлять новое
    handle_pay(call, edit_message=True)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "check_payment")
def check_payment_callback(call: CallbackQuery):
    from django.conf import settings
    from bot.models import User
    from django.utils import timezone
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    bot.answer_callback_query(call.id)
    user = User.objects.filter(telegram_id=str(call.from_user.id)).first()
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Назад", callback_data="back_to_menu"))
    
    if not user:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="Пользователь не найден. Пожалуйста, начните с команды /start",
            reply_markup=markup
        )
        return
        
    if not user.operation_id:
        try:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="У вас нет активного платежа. Пожалуйста, нажмите кнопку 'Оплатить' для создания нового платежа.",
                reply_markup=markup
            )
        except Exception:
            bot.send_message(
                call.from_user.id, 
                "У вас нет активного платежа. Пожалуйста, нажмите кнопку 'Оплатить' для создания нового платежа.", 
                reply_markup=markup
            )
        return

    api_url = f"https://enter.tochka.com/uapi/acquiring/v1.0/payments/{user.operation_id}"
    headers = {"Authorization": f"Bearer {settings.TOCHKA_API_TOKEN}"}
    
    try:
        resp = requests.get(api_url, headers=headers)
        if resp.status_code != 200:
            logger.error(f"Ошибка API Точка при проверке платежа: {resp.status_code} {resp.text}")
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="Произошла ошибка при проверке платежа. Пожалуйста, попробуйте позже или обратитесь в поддержку @it_jget",
                reply_markup=markup
            )
            return
            
        data = resp.json().get('Data', {})
        operation_list = data.get('Operation')
        
        if isinstance(operation_list, list) and operation_list:
            status = operation_list[0].get('status')
            amount = operation_list[0].get('amount')
        else:
            status = data.get('status')
            amount = data.get('amount')
            
        if not status:
            logger.error(f"Статус платежа не найден в ответе API: {data}")
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="Не удалось получить статус платежа. Пожалуйста, попробуйте позже или обратитесь в поддержку @it_jget",
                reply_markup=markup
            )
            return
            
        if status == 'APPROVED':
            user.operation_id = None
            now = timezone.now()
            if user.subscription_end and user.subscription_end > now:
                user.subscription_end = user.subscription_end + timezone.timedelta(days=30)
            else:
                user.subscription_end = now + timezone.timedelta(days=30)
            user.is_subscribed = True
            user.save()
            
            try:
                send_invite_link(user.telegram_id)
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=THANKS_PAYMENT,
                    reply_markup=markup
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке ссылки-приглашения: {e}")
                bot.send_message(
                    call.from_user.id,
                    THANKS_PAYMENT,
                    reply_markup=markup
                )
        elif status in ['REJECTED', 'CANCELLED', 'EXPIRED']:
            user.operation_id = None
            user.save()
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="Платеж был отменен или отклонен. Пожалуйста, попробуйте создать новый платеж.",
                reply_markup=markup
            )
        else:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="Платеж все еще в обработке. Пожалуйста, подождите несколько минут и проверьте снова. Если проблема сохраняется более 3 часов после оплаты - напишите нам @it_jget",
                reply_markup=markup
            )
    except Exception as e:
        logger.exception(f"Ошибка при проверке статуса платежа: {e}")
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="Произошла ошибка при проверке платежа. Пожалуйста, попробуйте позже или обратитесь в поддержку @it_jget",
            reply_markup=markup
        )

@bot.message_handler(commands=['promo'])
def ask_promo(message: Message):
    bot.send_message(message.from_user.id, "Введите промокод:")
    bot.register_next_step_handler(message, activate_promo)

def activate_promo(message: Message):
    code = message.text.strip()
    promo = PromoCode.objects.filter(code=code, is_used=False).first()
    if not promo:
        bot.send_message(message.from_user.id, "Промокод не найден или уже использован.")
        return
    user, _ = User.objects.get_or_create(telegram_id=str(message.from_user.id))
    from django.utils import timezone
    now = timezone.now()
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

@bot.callback_query_handler(func=lambda call: call.data == "check_promo")
def check_promo_callback(call: CallbackQuery):
    bot.send_message(call.from_user.id, "Введите промокод:")
    bot.register_next_step_handler(call.message, activate_promo) 

@bot.callback_query_handler(func=lambda call: call.data == "check_status")
def check_status_callback(call: CallbackQuery):
    from bot.models import User
    from django.utils import timezone
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    user = User.objects.filter(telegram_id=str(call.from_user.id)).first()
    if user and user.is_subscribed and user.subscription_end and user.subscription_end > timezone.now():
        date = user.subscription_end.strftime('%d.%m.%Y %H:%M')
        text = f"Ваша подписка активна до {date}."
    else:
        text = "У вас нет активной подписки."
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Назад", callback_data="back_to_menu"))
    try:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=text,
            reply_markup=markup
        )
    except Exception:
        bot.send_message(call.from_user.id, text, reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_menu")
def back_to_menu_callback(call: CallbackQuery):
    # Повторно показываем стартовое меню с кнопками через edit_message_text
    user = User.objects.filter(telegram_id=str(call.from_user.id)).first()
    from bot.texts import START_TEXT
    from django.utils import timezone
    if user and user.is_subscribed and user.subscription_end and user.subscription_end > timezone.now():
        button_text = "Продлить подписку"
        purpose = "Продление подписки"
    else:
        button_text = "Оплатить"
        purpose = "Оплата подписки"
    payment_link, operation_id, error = create_tochka_payment_link_with_receipt(user.telegram_id, 1, purpose, user.email) if user and user.email else (None, None, None)
    markup = InlineKeyboardMarkup()
    if payment_link:
        markup.add(InlineKeyboardButton(button_text, url=payment_link))
    markup.add(InlineKeyboardButton("Проверить оплату", callback_data="check_payment"))
    markup.add(InlineKeyboardButton("Ввести промокод", callback_data="check_promo"))
    markup.add(InlineKeyboardButton("Статус подписки", callback_data="check_status"))
    try:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=START_TEXT,
            reply_markup=markup
        )
    except Exception:
        bot.send_message(call.from_user.id, START_TEXT, reply_markup=markup)
    bot.answer_callback_query(call.id) 