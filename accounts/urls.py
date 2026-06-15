from django.urls import path

from accounts.views import ChangePasswordView, CsrfView, LoginView, LogoutView, MeView

urlpatterns = [
    path("csrf/", CsrfView.as_view()),
    path("login/", LoginView.as_view()),
    path("logout/", LogoutView.as_view()),
    path("me/", MeView.as_view()),
    path("change-password/", ChangePasswordView.as_view()),
]
