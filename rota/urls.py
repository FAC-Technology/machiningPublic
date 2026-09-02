from django.urls import path

from . import views

app_name = "rota"

urlpatterns = [
    path("", views.rota_week, name="week"),
    path("save/", views.save_rota, name="save"),
    path("suggest/", views.suggest_rota, name="suggest"),
    path("notify/", views.notify_rota, name="notify"),
]
