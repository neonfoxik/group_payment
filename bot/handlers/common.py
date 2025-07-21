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
            logger.error(f"Не удалось получить merchantId: {error}")
            return None, None, f"Не удалось получить merchantId: {error}"

    url = "https://enter.tochka.com/uapi/acquiring/v1.0/payments_with_receipt"
    
    payload = {
        "Data": {
            "customerCode": settings.TOCHKA_CUSTOMER_CODE,
            "merchantId": merchant_id,
            "amount": amount,
            "purpose": purpose,
            "paymentMode": ["sbp", "card"],
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
    logger.info(f"Создаем новую ссылку на оплату для пользователя {user_id}")
    logger.info(f"Payload: {payload}")
    
    headers = {
        "Authorization": f"Bearer {settings.TOCHKA_API_TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        logger.info(f"Ответ API Точка: {response.status_code} {response.text}")
        
        if response.status_code == 200:
            data = response.json().get('Data', {})
            operation_id = data.get('operationId')
            payment_link = data.get('paymentLink')
            
            if operation_id and payment_link:
                logger.info(f"Успешно создана ссылка на оплату: {payment_link}")
                return payment_link, operation_id, None
            else:
                error_msg = "Не удалось получить operationId или paymentLink из ответа API"
                logger.error(f"{error_msg}. Ответ: {data}")
                return None, None, error_msg
        else:
            error_msg = f"Ошибка API Точка: {response.status_code} {response.text}"
            logger.error(error_msg)
            return None, None, error_msg
            
    except Exception as e:
        error_msg = f"Исключение при создании ссылки на оплату: {str(e)}"
        logger.error(error_msg)
        return None, None, error_msg


def send_invite_link(user_id):
    from django.conf import settings
    try:
        group_id = settings.GROUP_ID
        logger.info(f"Попытка создания ссылки для приватной группы {group_id}")
        
        # Проверяем права бота и тип группы
        try:
            chat_info = bot.get_chat(group_id)
            logger.info(f"Тип группы: {chat_info.type}")
            logger.info(f"Название группы: {chat_info.title}")
            
            if chat_info.type not in ['group', 'supergroup']:
                logger.error(f"Неверный тип чата: {chat_info.type}")
                bot.send_message(settings.OWNER_ID, f"❗️ Ошибка: ID {group_id} не является группой")
                return None
            
            bot_member = bot.get_chat_member(group_id, bot.get_me().id)
            logger.info(f"Статус бота в группе: {bot_member.status}")
            
            if bot_member.status not in ['administrator', 'creator']:
                logger.error("У бота недостаточно прав")
                bot.send_message(settings.OWNER_ID, f"❗️ Бот должен быть администратором группы. Текущий статус: {bot_member.status}")
                return None
                
        except Exception as e:
            logger.error(f"Ошибка при проверке группы: {e}")
            bot.send_message(settings.OWNER_ID, f"❗️ Ошибка при проверке группы: {str(e)}")
            return None

        # Создаем ссылку для приватной группы
        try:
            # Создаем бессрочную ссылку с ограничением на один переход
            invite = bot.create_chat_invite_link(
                chat_id=group_id,
                name=f"Invite for user {user_id}",  # Добавляем имя для отслеживания
                member_limit=1,  # Ограничение на один переход
                expire_date=None,  # Бессрочная ссылка
                creates_join_request=False  # Разрешаем прямой вход без запроса
            )
            
            if not invite or not invite.invite_link:
                logger.error("Не удалось создать ссылку")
                return None
            
            logger.info(f"Создана ссылка: {invite.invite_link}")
            logger.info(f"Параметры: name={invite.name}, limit={invite.member_limit}, expires={invite.expire_date}")
            
            return invite.invite_link
                
        except Exception as e:
            error_msg = f"Ошибка при создании ссылки: {str(e)}"
            logger.error(error_msg)
            bot.send_message(settings.OWNER_ID, f"❗️ {error_msg}\nUser ID: {user_id}\nGroup ID: {group_id}")
            return None
            
    except Exception as e:
        logger.error(f"Общая ошибка при создании инвайт-ссылки: {e}")
        bot.send_message(settings.OWNER_ID, f"❗️ Ошибка при создании инвайт-ссылки для пользователя {user_id}: {e}")
        return None



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

def get_payment_link_for_user(user_id, amount=1000, purpose="Оплата подписки"):
    from bot.models import User
    user = User.objects.filter(telegram_id=str(user_id)).first()
    if not user or not user.email:
        return None, None, "Email пользователя не найден. Пожалуйста, укажите email через /email."
    
    # Всегда создаем новую ссылку, если нет активной
    if not user.operation_id:
        payment_link, operation_id, error = create_tochka_payment_link_with_receipt(user_id, amount, purpose, user.email)
        if operation_id:
            user.operation_id = operation_id
            user.save()
        return payment_link, operation_id, error
    else:
        # Если есть активный платеж, возвращаем его ссылку
        payment_link = f"https://enter.tochka.com/uapi/acquiring/v1.0/payments_with_receipt/{user.operation_id}"
        return payment_link, user.operation_id, None

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
    payment_link, operation_id, error = create_tochka_payment_link_with_receipt(user.telegram_id, 1000, purpose, user.email)
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

def check_payment_status(operation_id):
    """Проверяет статус платежа и возвращает (status, error)"""
    from django.conf import settings
    api_url = f"https://enter.tochka.com/uapi/acquiring/v1.0/payments/{operation_id}"
    headers = {"Authorization": f"Bearer {settings.TOCHKA_API_TOKEN}"}
    
    try:
        resp = requests.get(api_url, headers=headers)
        if resp.status_code != 200:
            logger.error(f"Ошибка API Точка при проверке платежа: {resp.status_code} {resp.text}")
            return None, f"Ошибка API Точка: {resp.status_code}"
            
        data = resp.json().get('Data', {})
        operation_list = data.get('Operation')
        
        if isinstance(operation_list, list) and operation_list:
            status = operation_list[0].get('status')
        else:
            status = data.get('status')
            
        if not status:
            logger.error(f"Статус платежа не найден в ответе API: {data}")
            return None, "Статус платежа не найден"
            
        return status, None
        
    except Exception as e:
        logger.error(f"Ошибка при проверке статуса платежа: {e}")
        return None, str(e)

def remove_from_blacklist(user_id):
    """Удаляет пользователя из черного списка группы"""
    from django.conf import settings
    try:
        group_id = settings.GROUP_ID
        logger.info(f"Попытка удаления пользователя {user_id} из черного списка группы {group_id}")
        
        try:
            # Пробуем разблокировать пользователя
            bot.unban_chat_member(
                chat_id=group_id,
                user_id=user_id,
                only_if_banned=True  # Разблокируем только если пользователь действительно заблокирован
            )
            logger.info(f"Пользователь {user_id} успешно удален из черного списка")
            return True
        except Exception as e:
            logger.info(f"Пользователь {user_id} не был в черном списке или произошла ошибка: {e}")
            return False
            
    except Exception as e:
        logger.error(f"Ошибка при удалении из черного списка: {e}")
        return False

def check_user_in_group(user_id):
    """Проверяет, находится ли пользователь в группе"""
    from django.conf import settings
    try:
        member = bot.get_chat_member(settings.GROUP_ID, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Ошибка при проверке членства пользователя {user_id} в группе: {e}")
        return False

def handle_successful_payment(user, call=None, message=None):
    """Обрабатывает успешную оплату"""
    from django.utils import timezone
    user.operation_id = None
    now = timezone.now()
    if user.subscription_end and user.subscription_end > now:
        user.subscription_end = user.subscription_end + timezone.timedelta(days=30)
    else:
        user.subscription_end = now + timezone.timedelta(days=30)
    user.is_subscribed = True
    user.save()
    
    # Удаляем пользователя из черного списка если он там есть
    remove_from_blacklist(user.telegram_id)
    
    # Проверяем, находится ли пользователь уже в группе
    if check_user_in_group(user.telegram_id):
        thanks_text = f"Спасибо за оплату! Ваша подписка продлена до {user.subscription_end.strftime('%d.%m.%Y')}."
    else:
        invite_link = send_invite_link(user.telegram_id)
        if invite_link:
            thanks_text = THANKS_PAYMENT.format(invite_link=invite_link)
        else:
            thanks_text = "Спасибо за оплату! Произошла ошибка при создании ссылки для вступления. Пожалуйста, обратитесь к администратору @it_jget"
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Назад", callback_data="back_to_menu"))
    
    if call:
        try:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=thanks_text,
                reply_markup=markup
            )
        except Exception:
            bot.send_message(call.from_user.id, thanks_text, reply_markup=markup)
    elif message:
        bot.send_message(message.from_user.id, thanks_text, reply_markup=markup)

def get_existing_payment_link(operation_id):
    """Получает ссылку на оплату для существующего платежа"""
    from django.conf import settings
    api_url = f"https://enter.tochka.com/uapi/acquiring/v1.0/payments/{operation_id}"
    headers = {"Authorization": f"Bearer {settings.TOCHKA_API_TOKEN}"}
    
    try:
        response = requests.get(api_url, headers=headers)
        if response.status_code == 200:
            data = response.json().get('Data', {})
            if isinstance(data.get('Operation'), list):
                payment_link = data['Operation'][0].get('paymentLink')
            else:
                payment_link = data.get('paymentLink')
            
            if payment_link:
                return payment_link
            else:
                logger.error(f"Не удалось получить paymentLink из ответа API: {data}")
                return None
        else:
            logger.error(f"Ошибка при получении ссылки на оплату: {response.status_code} {response.text}")
            return None
    except Exception as e:
        logger.error(f"Исключение при получении ссылки на оплату: {e}")
        return None

def start_registration(message: Message):
    user, created = register_user(message)
    from bot.texts import START_TEXT
    from bot.models import User
    from django.utils import timezone
    
    logger.info(f"Запуск start_registration для пользователя {message.from_user.id}")
    
    if not user.email:
        logger.info(f"У пользователя {message.from_user.id} нет email")
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Отмена", callback_data="cancel_email"))
        bot.send_message(message.from_user.id, "Пожалуйста, введите ваш email для получения чека:", reply_markup=markup)
        bot.register_next_step_handler(message, save_email)
        return

    # Проверяем статус подписки
    is_active = user.is_subscribed and user.subscription_end and user.subscription_end > timezone.now()
    button_text = "Продлить подписку" if is_active else "Оплатить"
    purpose = "Продление подписки" if is_active else "Оплата подписки"
    
    logger.info(f"Статус подписки пользователя {message.from_user.id}: {'активна' if is_active else 'неактивна'}")
    logger.info(f"Текущий operation_id: {user.operation_id}")

    markup = InlineKeyboardMarkup()
    payment_link = None

    # Проверяем существующий платеж
    if user.operation_id:
        status, error = check_payment_status(user.operation_id)
        logger.info(f"Статус платежа {user.operation_id}: {status}")
        
        if status == 'APPROVED':
            # Если оплачен - выдаем ссылку на группу
            handle_successful_payment(user, message=message)
            return
        elif status == 'REJECTED' or status == 'EXPIRED' or status == 'CANCELLED':
            # Только если платеж точно отменен/отклонен/истек - создаем новый
            logger.info("Платеж отменен/отклонен/истек, создаем новый")
            user.operation_id = None
            user.save()
            payment_link, operation_id, error = create_tochka_payment_link_with_receipt(message.from_user.id, 1000, purpose, user.email)
            if operation_id:
                user.operation_id = operation_id
                user.save()
        else:
            # В любом другом случае (PENDING, PROCESSING или ошибка проверки) - получаем существующую ссылку
            logger.info("Получаем существующую ссылку")
            payment_link = get_existing_payment_link(user.operation_id)
            if not payment_link:
                # Если не удалось получить существующую ссылку - создаем новую
                logger.info("Не удалось получить существующую ссылку, создаем новую")
                payment_link, operation_id, error = create_tochka_payment_link_with_receipt(message.from_user.id, 1000, purpose, user.email)
                if operation_id:
                    user.operation_id = operation_id
                    user.save()
    else:
        # Если нет operation_id - создаем новый платеж
        logger.info("Нет operation_id, создаем новый платеж")
        payment_link, operation_id, error = create_tochka_payment_link_with_receipt(message.from_user.id, 1000, purpose, user.email)
        if operation_id:
            user.operation_id = operation_id
            user.save()

    # Формируем сообщение с кнопками
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
    logger.info(f"Отправлено стартовое сообщение пользователю {message.from_user.id}")

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
    amount = 1000
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
        # Если нет активного платежа, создаем новый
        if not user.email:
            try:
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="Перед оплатой укажите ваш email с помощью команды /email",
                    reply_markup=markup
                )
            except Exception:
                bot.send_message(
                    call.from_user.id,
                    "Перед оплатой укажите ваш email с помощью команды /email",
                    reply_markup=markup
                )
            return

        # Определяем тип платежа
        is_active = user.is_subscribed and user.subscription_end and user.subscription_end > timezone.now()
        purpose = "Продление подписки" if is_active else "Оплата подписки"
        button_text = "Продлить подписку" if is_active else "Оплатить"

        # Создаем новую ссылку на оплату
        payment_link, operation_id, error = create_tochka_payment_link_with_receipt(user.telegram_id, 1000, purpose, user.email)
        if payment_link and operation_id:
            user.operation_id = operation_id
            user.save()
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(button_text, url=payment_link))
            markup.add(InlineKeyboardButton("Проверить оплату", callback_data="check_payment"))
            markup.add(InlineKeyboardButton("Назад", callback_data="back_to_menu"))
            try:
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=f"У вас нет активного платежа. Создана новая ссылка для оплаты.",
                    reply_markup=markup
                )
            except Exception:
                bot.send_message(
                    call.from_user.id,
                    f"У вас нет активного платежа. Создана новая ссылка для оплаты.",
                    reply_markup=markup
                )
            return
        else:
            error_text = f"Произошла ошибка при создании ссылки на оплату.\n{error if error else ''}"
            try:
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=error_text,
                    reply_markup=markup
                )
            except Exception:
                bot.send_message(call.from_user.id, error_text, reply_markup=markup)
            return

    # Проверяем статус существующего платежа
    status, error = check_payment_status(user.operation_id)
    logger.info(f"Проверка статуса платежа {user.operation_id}: {status}")
    
    if status == 'APPROVED':
        # Обрабатываем успешный платеж
        handle_successful_payment(user, call=call)
    elif status == 'REJECTED' or status == 'EXPIRED' or status == 'CANCELLED':
        # Только если платеж точно отменен/отклонен/истек - создаем новый
        user.operation_id = None
        user.save()
        
        is_active = user.is_subscribed and user.subscription_end and user.subscription_end > timezone.now()
        purpose = "Продление подписки" if is_active else "Оплата подписки"
        button_text = "Продлить подписку" if is_active else "Оплатить"
        
        payment_link, operation_id, error = create_tochka_payment_link_with_receipt(user.telegram_id, 1000, purpose, user.email)
        if payment_link and operation_id:
            user.operation_id = operation_id
            user.save()
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(button_text, url=payment_link))
            markup.add(InlineKeyboardButton("Проверить оплату", callback_data="check_payment"))
            markup.add(InlineKeyboardButton("Назад", callback_data="back_to_menu"))
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="Предыдущий платеж был отменен. Создана новая ссылка для оплаты.",
                reply_markup=markup
            )
        else:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"Ошибка при создании новой ссылки на оплату: {error if error else ''}",
                reply_markup=markup
            )
    else:
        # В любом другом случае (PENDING, PROCESSING или ошибка) - получаем существующую ссылку
        payment_link = get_existing_payment_link(user.operation_id)
        if payment_link:
            markup.add(InlineKeyboardButton("Перейти к оплате", url=payment_link))
        
        status_text = "Платеж находится в обработке. Пожалуйста, подождите или попробуйте проверить позже."
        if error:
            status_text = f"Произошла ошибка при проверке платежа: {error}"
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=status_text,
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
    
    # Удаляем пользователя из черного списка если он там есть
    remove_from_blacklist(message.from_user.id)
    
    # Проверяем, находится ли пользователь уже в группе
    if check_user_in_group(message.from_user.id):
        bot.send_message(
            message.from_user.id,
            f"Промокод активирован! Ваша подписка продлена до {user.subscription_end.strftime('%d.%m.%Y')}."
        )
    else:
        # Создаем и отправляем одноразовую ссылку
        invite_link = send_invite_link(message.from_user.id)
        if invite_link:
            bot.send_message(
                message.from_user.id, 
                f"Промокод активирован! Вам выдан бесплатный доступ на 30 дней.\n\nВот ваша одноразовая ссылка для вступления в группу: {invite_link}"
            )
        else:
            bot.send_message(
                message.from_user.id,
                "Промокод активирован! Вам выдан бесплатный доступ на 30 дней.\n\nК сожалению, произошла ошибка при создании ссылки для вступления. Пожалуйста, обратитесь к администратору @it_jget"
            )

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
    user = User.objects.filter(telegram_id=str(call.from_user.id)).first()
    from bot.texts import START_TEXT
    from django.utils import timezone

    # Проверяем статус подписки
    is_active = user.is_subscribed and user.subscription_end and user.subscription_end > timezone.now()
    button_text = "Продлить подписку" if is_active else "Оплатить"
    purpose = "Продление подписки" if is_active else "Оплата подписки"

    markup = InlineKeyboardMarkup()
    payment_link = None

    # Проверяем существующий платеж
    if user.operation_id:
        status, error = check_payment_status(user.operation_id)
        logger.info(f"Проверка статуса платежа {user.operation_id} при возврате в меню: {status}")
        
        if status == 'APPROVED':
            # Если оплачен - выдаем ссылку на группу
            handle_successful_payment(user, call=call)
            return
        elif status == 'REJECTED' or status == 'EXPIRED' or status == 'CANCELLED':
            # Только если платеж точно отменен/отклонен/истек - создаем новый
            logger.info("Платеж отменен/отклонен/истек, создаем новый")
            user.operation_id = None
            user.save()
            payment_link, operation_id, error = create_tochka_payment_link_with_receipt(user.telegram_id, 1000, purpose, user.email)
            if operation_id:
                user.operation_id = operation_id
                user.save()
        else:
            # В любом другом случае (PENDING, PROCESSING или ошибка проверки) - получаем существующую ссылку
            logger.info("Получаем существующую ссылку")
            payment_link = get_existing_payment_link(user.operation_id)
            if not payment_link:
                # Если не удалось получить существующую ссылку - создаем новую
                logger.info("Не удалось получить существующую ссылку, создаем новую")
                payment_link, operation_id, error = create_tochka_payment_link_with_receipt(user.telegram_id, 1000, purpose, user.email)
                if operation_id:
                    user.operation_id = operation_id
                    user.save()
    else:
        # Если нет operation_id - создаем новый платеж
        logger.info("Нет operation_id, создаем новый платеж")
        payment_link, operation_id, error = create_tochka_payment_link_with_receipt(user.telegram_id, 1000, purpose, user.email)
        if operation_id:
            user.operation_id = operation_id
            user.save()

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

# Тестовый обработчик для создания инвайт-ссылок
@bot.message_handler(commands=['link'])
def test_invite_link(message: Message):
    """Тестовая команда для создания инвайт-ссылок"""
    from django.conf import settings
    
    # Проверяем, является ли пользователь администратором
    if str(message.from_user.id) != str(settings.OWNER_ID):
        bot.reply_to(message, "Эта команда доступна только администратору.")
        return
        
    invite_link = send_invite_link(message.from_user.id)
    if invite_link:
        bot.reply_to(
            message,
            f"✅ Тестовая ссылка создана успешно!\n\n"
            f"Ссылка: {invite_link}\n\n"
            f"Попробуйте перейти по ней и сообщить результат."
        )
    else:
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Повторить", callback_data="retry_link"))
        bot.reply_to(
            message,
            "❌ Ошибка при создании ссылки. Проверьте права бота в группе и настройки.",
            reply_markup=markup
        )

@bot.callback_query_handler(func=lambda call: call.data == "retry_link")
def retry_link_callback(call: CallbackQuery):
    """Повторная попытка создания ссылки"""
    invite_link = send_invite_link(call.from_user.id)
    if invite_link:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"✅ Тестовая ссылка создана успешно!\n\n"
                 f"Ссылка: {invite_link}\n\n"
                 f"Попробуйте перейти по ней и сообщить результат."
        )
    else:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Повторить", callback_data="retry_link"))
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="❌ Ошибка при создании ссылки. Проверьте права бота в группе и настройки.",
            reply_markup=markup
        ) 