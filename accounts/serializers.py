from rest_framework import serializers

from accounts.models import User


class AuthUserSerializer(serializers.ModelSerializer):
    requiereCambioPassword = serializers.BooleanField(source="requiere_cambio_password")
    personalId = serializers.CharField(source="personal_id", allow_null=True)

    class Meta:
        model = User
        fields = ["id", "email", "nombre", "rol", "requiereCambioPassword", "bloqueado", "personalId"]
