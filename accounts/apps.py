from django.apps import AppConfig
from django.db.models.signals import post_migrate


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        post_migrate.connect(sync_demo_auth_groups, dispatch_uid="sync_demo_auth_groups")


def sync_demo_auth_groups(**kwargs):
    from demo.seed import sync_demo_groups_and_permissions

    sync_demo_groups_and_permissions()
