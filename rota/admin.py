from django.contrib import admin

from .models import RotaAssignment


@admin.register(RotaAssignment)
class RotaAssignmentAdmin(admin.ModelAdmin):
    list_display = ("date", "slot", "machinist", "notes")
    list_filter = ("date",)
