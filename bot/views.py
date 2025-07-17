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
from bot.texts import START_TEXT, PAY_TEXT
from telebot.types import Message, CallbackQuery
from django.core.mail import send_mail

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
@require_http_methods(["POST", "GET"])
def tochka_payment_webhook(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        print('Получен GET-запрос на tochka_payment_webhook')
        return JsonResponse({"status": "ok (GET-запрос, оплата не подтверждена)"}, status=200)
    try:
        print('Получен вебхук от Точки')
        user_id = request.GET.get('user_id')
        data = json.loads(request.body.decode('utf-8'))
        operation_id = data.get('operationId')
        print(f'user_id из запроса: {user_id}, operation_id из запроса: {operation_id}')
        if not operation_id or not user_id:
            print('operationId или user_id отсутствует в запросе')
            return JsonResponse({"error": "operationId or user_id missing"}, status=400)
        api_url = f"https://enter.tochka.com/uapi/acquiring/v1.0/payments/{operation_id}"
        headers = {"Authorization": f"Bearer {settings.TOCHKA_API_TOKEN}"}
        resp = requests.get(api_url, headers=headers)
        print('tochka_payment_webhook resp:', resp.text)  # Логируем ответ от Точки
        if resp.status_code == 200:
            data = resp.json().get('Data', {})
            operation_list = data.get('Operation')
            if isinstance(operation_list, list) and operation_list:
                status = operation_list[0].get('status')
            else:
                status = data.get('status')
            print(f'Статус оплаты: {status}')
            if status == 'APPROVED':
                print(f'Оплата подтверждена, отправляю ссылку пользователю {user_id}')
                send_invite_link(user_id)
                return JsonResponse({"status": "invite sent"})
            else:
                print(f'Оплата не подтверждена, статус: {status}')
                return JsonResponse({"status": f"not approved: {status}"})
        else:
            print(f'Ошибка при запросе статуса оплаты: {resp.status_code}')
            return JsonResponse({"error": f"tochka api error: {resp.status_code}"}, status=500)
    except Exception as e:
        print(f'Ошибка в обработчике tochka_payment_webhook: {e}')
        return JsonResponse({"error": str(e)}, status=500)

@require_GET
def index(request: HttpRequest) -> JsonResponse:
    bot.set_webhook(url=f"{settings.HOOK}/bot/payment_webhook/")
    bot.send_message(settings.OWNER_ID, "webhook set")
    return JsonResponse({"message": "webhook set"}, status=200)