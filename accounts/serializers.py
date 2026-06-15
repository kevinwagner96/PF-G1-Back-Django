from rest_framework import serializers

from accounts.models import User
from accounts.permissions import get_explicit_permissions


class AuthUserSerializer(serializers.ModelSerializer):
    requiereCambioPassword = serializers.BooleanField(source="requiere_cambio_password")
    personalId = serializers.CharField(source="personal_id", allow_null=True)
    permissions = serializers.SerializerMethodField()

    def get_permissions(self, obj):
        return get_explicit_permissions(obj)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "nombre",
            "rol",
            "requiereCambioPassword",
            "bloqueado",
            "personalId",
            "permissions",
        ]
