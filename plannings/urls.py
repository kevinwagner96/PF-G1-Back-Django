from django.urls import path

from plannings.views import (
    ActivePlanningView,
    PlanningApproveView,
    PlanningDetailView,
    PlanningEditView,
    PlanningHistoryView,
    PlanningListCreateView,
    PlanningLockView,
    PlanningPreflightView,
    PlanningRecoverView,
    SchedulerCallbackView,
)

urlpatterns = [
    path("plannings/", PlanningListCreateView.as_view()),
    path("plannings/active/", ActivePlanningView.as_view()),
    path("plannings/preflight/", PlanningPreflightView.as_view()),
    path("plannings/<str:scheduler_uuid>/", PlanningDetailView.as_view()),
    path("plannings/<str:scheduler_uuid>/approve/", PlanningApproveView.as_view()),
    path("plannings/<str:scheduler_uuid>/lock/", PlanningLockView.as_view()),
    path("plannings/<str:scheduler_uuid>/lock/recover/", PlanningRecoverView.as_view()),
    path("plannings/<str:scheduler_uuid>/edit/", PlanningEditView.as_view()),
    path("plannings/<str:scheduler_uuid>/history/", PlanningHistoryView.as_view()),
    path("scheduler/callback/", SchedulerCallbackView.as_view()),
]
