from django.urls import path
from bot import views

app_name = 'bot'

urlpatterns = [
    path('', views.index, name="index"),
    path('set_webhook/', views.set_webhook, name="set_webhook"),
    path('status/', views.status, name="status"),
    path('payment_webhook/', views.payment_webhook, name="payment_webhook"),
]
