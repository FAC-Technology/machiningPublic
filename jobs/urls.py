from django.urls import path

from . import views

app_name = "jobs"

urlpatterns = [
    path("", views.home, name="home"),
    path("whoami/", views.choose_person, name="whoami"),
    path("submit/", views.submit_page, name="submit"),
    path("engineer/", views.submit_page, name="engineer"),
    path("queue/", views.queue_page, name="queue"),
    path("history/", views.history_page, name="history"),
    path("setup/", views.setup_page, name="setup"),
    path("setup/person/<int:pk>/toggle/", views.toggle_person, name="toggle_person"),
    path("setup/panel/<int:pk>/toggle/", views.toggle_panel, name="toggle_panel"),
    path("setup/panel/<int:pk>/delete/", views.delete_panel, name="delete_panel"),
    path("setup/project/<int:pk>/toggle/", views.toggle_project, name="toggle_project"),
    path("setup/project/<int:pk>/delete/", views.delete_project, name="delete_project"),
    path("setup/destination/<int:pk>/toggle/", views.toggle_destination, name="toggle_destination"),
    path("setup/destination/<int:pk>/delete/", views.delete_destination, name="delete_destination"),
    path("jobs/<str:job_id>/", views.job_detail, name="detail"),
    path("jobs/<str:job_id>/edit/", views.edit_job, name="edit"),
    path("jobs/<str:job_id>/update/", views.update_job, name="update"),
    path("jobs/<str:job_id>/file/<str:kind>/", views.job_file_view, name="file"),
]
