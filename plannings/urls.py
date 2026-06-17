from django.urls import path

from plannings.views import (
    ActivePlanningView,
    PlanningApproveView,
    PlanningDetailView,
    PlanningListCreateView,
    PlanningPreflightView,
    PlanningRejectView,
    SchedulerCallbackView,
)

urlpatterns = [
    path("plannings/", PlanningListCreateView.as_view()),
    path("plannings/active/", ActivePlanningView.as_view()),
    path("plannings/preflight/", PlanningPreflightView.as_view()),
    path("plannings/<str:scheduler_uuid>/", PlanningDetailView.as_view()),
    path("plannings/<str:scheduler_uuid>/approve/", PlanningApproveView.as_view()),
    path("plannings/<str:scheduler_uuid>/reject/", PlanningRejectView.as_view()),
    path("scheduler/callback/", SchedulerCallbackView.as_view()),
]
