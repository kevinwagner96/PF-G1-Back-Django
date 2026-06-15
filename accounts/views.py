from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.middleware.csrf import get_token
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.serializers import AuthUserSerializer


class CsrfView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({"csrfToken": get_token(request)})


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get("email", "")
        password = request.data.get("password", "")
        user = authenticate(request, username=email, password=password)
        if user is None:
            return Response({"detail": "Credenciales incorrectas"}, status=status.HTTP_401_UNAUTHORIZED)
        if getattr(user, "bloqueado", False):
            return Response(
                {"detail": "Cuenta bloqueada. Contacte al administrador."},
                status=status.HTTP_403_FORBIDDEN,
            )
        login(request, user)
        return Response({"user": AuthUserSerializer(user).data})


class LogoutView(APIView):
    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    def get(self, request):
        return Response({"user": AuthUserSerializer(request.user).data})


class ChangePasswordView(APIView):
    def post(self, request):
        new_password = request.data.get("newPassword") or request.data.get("new_password")
        if not new_password:
            return Response({"detail": "La nueva contraseña es obligatoria"}, status=status.HTTP_400_BAD_REQUEST)
        request.user.set_password(new_password)
        request.user.requiere_cambio_password = False
        request.user.save(update_fields=["password", "requiere_cambio_password"])
        update_session_auth_hash(request, request.user)
        return Response({"user": AuthUserSerializer(request.user).data})
