"""Common"""
from django.http import JsonResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.utils import timezone
from datetime import timedelta
import json
from bot.models import User
from bot.bot_instance import bot
from django.conf import settings
import requests
from bot.handlers.common import (
    register_user, get_status_text, get_payment_link_for_user, send_invite_link
)
from bot.keyboards import main_markup
from bot.texts import START_TEXT
from telebot.types import Message, CallbackQuery
from django.core.mail import send_mail
import logging

logger = logging.getLogger(__name__)

# Команда /start

def start_registration(message: Message):
    user, created = register_user(message)
    bot.send_message(
        message.from_user.id,
        START_TEXT,
        reply_markup=main_markup
    )

start = bot.message_handler(commands=["start"])(start_registration)

# Кнопка "Статус подписки"
def check_subscription(call: CallbackQuery):
    user = User.objects.get(telegram_id=str(call.from_user.id))
    status_text = get_status_text(user)
    bot.answer_callback_query(call.id)
    bot.send_message(call.from_user.id, status_text, reply_markup=main_markup)

profile = bot.callback_query_handler(lambda c: c.data == "check_subscription")(check_subscription)

# Кнопка "Оплатить подписку"
def pay_subscription(call: CallbackQuery):
    user_id = call.from_user.id
    payment_link, operation_id, error = get_payment_link_for_user(user_id)
    if payment_link:
        user = User.objects.filter(telegram_id=str(user_id)).first()
        if user and operation_id:
            user.operation_id = operation_id
            user.save()
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Оплатить", url=payment_link))
        bot.send_message(user_id, PAY_TEXT, reply_markup=markup)
    elif error:
        bot.send_message(user_id, f"Ошибка при создании ссылки на оплату: {error}")
    else:
        bot.send_message(user_id, "Ошибка при создании ссылки на оплату.")
    bot.answer_callback_query(call.id)

pay = bot.callback_query_handler(lambda c: c.data == "pay_subscription")(pay_subscription)

# --- Оставшиеся Django views (webhook, index и т.д.) ---
@require_GET
def set_webhook(request: HttpRequest) -> JsonResponse:
    bot.set_webhook(url=f"{settings.HOOK}/bot/payment_webhook/")
    bot.send_message(settings.OWNER_ID, "webhook set")
    return JsonResponse({"message": "OK"}, status=200)

@require_GET
def status(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"message": "OK"}, status=200)

@csrf_exempt
@require_POST
def payment_webhook(request: HttpRequest) -> JsonResponse:
    try:
        json_str = request.body.decode('utf-8')
        print('payment_webhook json_str:', json_str)  # Логируем тело запроса
        import telebot
        bot.process_new_updates([telebot.types.Update.de_json(json_str)])
        return JsonResponse({"status": "ok"})
    except Exception as e:
        import traceback
        print('payment_webhook exception:', traceback.format_exc())  # Логируем traceback
        return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def tochka_payment_webhook(request: HttpRequest) -> JsonResponse:
    try:
        data = json.loads(request.body.decode('utf-8'))
        operation_id = data.get('operationId')
        status = data.get('status')
        user_id = request.GET.get('user_id')
        
        logger.info(f'Webhook: operation_id={operation_id}, status={status}, user_id={user_id}')
        
        if not operation_id:
            logger.error('operation_id отсутствует в запросе')
            return JsonResponse({"error": "operation_id missing"}, status=400)
            
        if not user_id:
            logger.error('user_id отсутствует в запросе')
            return JsonResponse({"error": "user_id missing"}, status=400)
            
        if not status:
            logger.error('status отсутствует в запросе')
            return JsonResponse({"error": "status missing"}, status=400)
            
        if status == 'APPROVED':
            # Активируем подписку пользователя
            from bot.models import User
            from django.utils import timezone
            user = User.objects.filter(telegram_id=str(user_id)).first()
            
            if not user:
                logger.error(f'Пользователь не найден: {user_id}')
                return JsonResponse({"error": "user not found"}, status=404)
                
            # Проверяем, что operation_id совпадает с сохраненным у пользователя
            if user.operation_id != operation_id:
                logger.error(f'Operation ID не совпадает: {operation_id} != {user.operation_id}')
                return JsonResponse({"error": "operation_id mismatch"}, status=400)
                
            now = timezone.now()
            if user.subscription_end and user.subscription_end > now:
                user.subscription_end = user.subscription_end + timezone.timedelta(days=30)
            else:
                user.subscription_end = now + timezone.timedelta(days=30)
            user.is_subscribed = True
            user.operation_id = None
            user.save()
            
            # Разбаниваем пользователя в группе
            try:
                from bot.management.commands.ban_expired import GROUP_ID
                bot.unban_chat_member(GROUP_ID, int(user_id))
            except Exception as e:
                logger.error(f'Ошибка при разбане пользователя {user_id}: {e}')
            
            # Отправляем инвайт
            invite_link = send_invite_link(user_id)
            if invite_link:
                return JsonResponse({"status": "success", "invite_sent": True})
            else:
                return JsonResponse({"status": "success", "invite_sent": False, "error": "invite link creation failed"})
        else:
            # Для остальных статусов просто логируем
            logger.info(f'Получен статус платежа: {status}')
            return JsonResponse({"status": "received", "payment_status": status})
            
    except json.JSONDecodeError as e:
        logger.error(f'Ошибка декодирования JSON в webhook: {e}')
        return JsonResponse({"error": "invalid json"}, status=400)
    except Exception as e:
        logger.exception(f'Ошибка в обработчике tochka_payment_webhook: {e}')
        return JsonResponse({"error": str(e)}, status=500)

@require_GET
def index(request: HttpRequest) -> JsonResponse:
    bot.set_webhook(url=f"{settings.HOOK}/bot/payment_webhook/")
    bot.send_message(settings.OWNER_ID, "webhook set")
    return JsonResponse({"message": "webhook set"}, status=200)

@require_GET
def set_tochka_webhook(request: HttpRequest) -> JsonResponse:
    import requests
    import json
    client_id = settings.TOCHKA_CLIENT_ID  # добавь в settings.py
    token = settings.TOCHKA_API_TOKEN
    webhook_url = f"{settings.HOOK}/bot/tochka_payment_webhook/"
    url = f"https://enter.tochka.com/uapi/webhook/v1.0/{client_id}"
    payload = json.dumps({
        "webhooksList": [
            "acquiringInternetPayment"
        ],
        "url": webhook_url
    })
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}'
    }
    try:
        resp = requests.request("PUT", url, headers=headers, data=payload)
        try:
            resp_json = resp.json()
        except Exception:
            resp_json = resp.text
        print(f"Ответ Точки на регистрацию вебхука: {resp_json}")
        if resp.status_code == 200 and isinstance(resp_json, dict) and not resp_json.get('code'):
            return JsonResponse({"status": "ok", "response": resp_json})
        else:
            return JsonResponse({"status": "error", "response": resp_json}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)