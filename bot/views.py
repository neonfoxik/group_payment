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
@require_http_methods(["POST"])
def tochka_payment_webhook(request: HttpRequest) -> JsonResponse:
    try:
        data = json.loads(request.body.decode('utf-8'))
        operation_id = data.get('operationId')
        status = data.get('status')
        user_id = request.GET.get('user_id')
        print(f'Webhook: operation_id={operation_id}, status={status}, user_id={user_id}')
        if not user_id:
            print('user_id отсутствует в запросе')
            return JsonResponse({"error": "user_id missing"}, status=400)
        if status == 'APPROVED':
            # Активируем подписку пользователя
            from bot.models import User
            from django.utils import timezone
            user = User.objects.filter(telegram_id=str(user_id)).first()
            now = timezone.now()
            if user:
                if user.subscription_end and user.subscription_end > now:
                    user.subscription_end = user.subscription_end + timezone.timedelta(days=30)
                else:
                    user.subscription_end = now + timezone.timedelta(days=30)
                user.is_subscribed = True
                user.last_operation_id = None  # сбрасываем после оплаты
                user.save()
                # Разбаниваем пользователя в группе
                try:
                    from bot.management.commands.ban_expired import GROUP_ID
                    bot.unban_chat_member(GROUP_ID, int(user_id))
                except Exception as e:
                    print(f'Ошибка при разбане пользователя {user_id}: {e}')
                send_invite_link(user_id)
                return JsonResponse({"status": "invite sent"})
            else:
                return JsonResponse({"status": f"not approved: {status}"})
    except Exception as e:
        print(f'Ошибка в обработчике tochka_payment_webhook: {e}')
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