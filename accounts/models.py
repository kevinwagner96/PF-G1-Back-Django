from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    email = models.EmailField(unique=True)
    nombre = models.CharField(max_length=255)
    rol = models.CharField(max_length=50)
    requiere_cambio_password = models.BooleanField(default=False)
    bloqueado = models.BooleanField(default=False)
    personal_id = models.CharField(max_length=36, blank=True, null=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username", "nombre"]

    class Meta:
        permissions = [("can_access_system_admin", "Can access system admin")]

    def __str__(self) -> str:
        return self.email
