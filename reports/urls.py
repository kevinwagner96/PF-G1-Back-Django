from django.urls import path

from reports.views import ReportsSummaryView

urlpatterns = [
    path("reports/summary/", ReportsSummaryView.as_view()),
]
