from django.urls import path

from surgeries.views import (
    MedicalStaffListView,
    OperatingRoomListView,
    PendingSurgeryListView,
    SurgeryListView,
)

urlpatterns = [
    path("surgeries/", SurgeryListView.as_view()),
    path("surgeries/pending/", PendingSurgeryListView.as_view()),
    path("operating-rooms/", OperatingRoomListView.as_view()),
    path("medical-staff/", MedicalStaffListView.as_view()),
]
