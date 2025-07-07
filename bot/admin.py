from django.contrib import admin
from .models import User

class UserAdmin(admin.ModelAdmin):
    list_display = ('user_tg_name', 'user_name', 'subscription_end', 'is_subscribed')
    search_fields = ('user_name', 'user_tg_name')
    ordering = ('-subscription_end',)

admin.site.register(User, UserAdmin)
