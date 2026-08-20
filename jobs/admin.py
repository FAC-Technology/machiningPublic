from django.contrib import admin

from .models import Destination, Job, Panel, Person, Project


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("initials", "is_engineer", "is_machinist", "is_admin", "is_active")
    fields = ("initials", "is_engineer", "is_machinist", "is_admin", "is_active")

    def save_model(self, request, obj, form, change):
        if not obj.name:
            obj.name = obj.initials
        super().save_model(request, obj, form, change)


@admin.register(Panel)
class PanelAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")


@admin.register(Destination)
class DestinationAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = (
        "job_id",
        "job_label",
        "priority",
        "status",
        "requested_by",
        "deadline",
        "panel",
        "project",
    )
    list_filter = ("status", "priority", "project")
    search_fields = ("job_id", "job_label", "job_name", "project__name")
