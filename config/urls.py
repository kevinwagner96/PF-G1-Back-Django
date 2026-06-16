from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("accounts.urls")),
    path("api/v1/", include("surgeries.urls")),
    path("api/v1/", include("plannings.urls")),
    path("api/v1/", include("reports.urls")),
    path("api/v1/demo/", include("demo.urls")),
    path("api/v1/health/", include("health.urls")),
]
