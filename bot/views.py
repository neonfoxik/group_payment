from django.http import JsonResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone
from datetime import timedelta
import json
from bot.models import User
from bot.bot_instance import bot
from django.conf import settings
from bot.handlers.common import start, pay_subscription, check_subscription, after_payment

@require_GET
def set_webhook(request: HttpRequest) -> JsonResponse:
    """Setting webhook."""
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
        import telebot
        bot.process_new_updates([telebot.types.Update.de_json(json_str)])
        return JsonResponse({"status": "ok"})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

@require_GET
def index(request: HttpRequest) -> JsonResponse:
    bot.set_webhook(url=f"{settings.HOOK}/bot/payment_webhook/")
    bot.send_message(settings.OWNER_ID, "webhook set")
    return JsonResponse({"message": "webhook set"}, status=200)