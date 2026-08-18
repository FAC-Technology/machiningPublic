from django.contrib import admin

from .models import Job, Panel, Person, Project


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("initials", "name", "is_engineer", "is_machinist", "is_admin", "is_active")


@admin.register(Panel)
class PanelAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
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
