from django.urls import path

from surgeries.views import (
    MedicalStaffListView,
    OperatingRoomListView,
    PendingSurgeryListView,
    SurgeryCancelView,
    SurgeryCatalogsView,
    SurgeryDetailView,
    SurgeryListView,
)

urlpatterns = [
    path("surgeries/", SurgeryListView.as_view()),
    path("surgeries/pending/", PendingSurgeryListView.as_view()),
    path("surgeries/<str:surgery_id>/", SurgeryDetailView.as_view()),
    path("surgeries/<str:surgery_id>/cancel/", SurgeryCancelView.as_view()),
    path("surgery-catalogs/", SurgeryCatalogsView.as_view()),
    path("operating-rooms/", OperatingRoomListView.as_view()),
    path("medical-staff/", MedicalStaffListView.as_view()),
]
