from django.urls import path

from demo.views import DemoResetView

urlpatterns = [
    path("reset/", DemoResetView.as_view()),
]
