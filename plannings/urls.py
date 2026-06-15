from django.urls import path

from plannings.views import (
    PlanningApproveView,
    PlanningDetailView,
    PlanningListCreateView,
    SchedulerCallbackView,
)

urlpatterns = [
    path("plannings/", PlanningListCreateView.as_view()),
    path("plannings/<str:scheduler_uuid>/", PlanningDetailView.as_view()),
    path("plannings/<str:scheduler_uuid>/approve/", PlanningApproveView.as_view()),
    path("scheduler/callback/", SchedulerCallbackView.as_view()),
]
