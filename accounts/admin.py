from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "display_name", "role", "email", "is_staff")
    list_filter = ("role", "is_staff", "is_superuser")
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Shop role", {"fields": ("role", "display_name")}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ("Shop role", {"fields": ("role", "display_name")}),
    )
