from django.db import models
from django.utils import timezone
import jsonfield


class User(models.Model):
    telegram_id = models.CharField(
        primary_key=True,
        max_length=50
    )
    user_tg_name = models.CharField(
        max_length=35,
        verbose_name='Имя аккаунта в телеграм',
        null=True,
        blank=True,
        default="none",
    )
    user_name = models.CharField(
        max_length=35,
        verbose_name='Имя',
        null=True,
        blank=True,
    )
    email = models.EmailField(
        max_length=255,
        verbose_name='Email',
        null=True,
        blank=True,
    )
    subscription_end = models.DateTimeField(null=True, blank=True, verbose_name='Дата окончания подписки')
    is_subscribed = models.BooleanField(default=False, verbose_name='Активна ли подписка')

    def __str__(self):
        return str(self.user_name)

    class Meta:
        verbose_name = 'Пользователь'
        verbose_name_plural = 'Пользователи'


class PromoCode(models.Model):
    code = models.CharField(max_length=32, unique=True)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    used_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    def __str__(self):
        return self.code
