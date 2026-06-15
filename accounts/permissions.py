from django.contrib.auth.models import AnonymousUser

CREATE_PLANNING_PERMISSION = "plannings.can_create_planning"
APPROVE_PLANNING_PERMISSION = "plannings.can_approve_planning"
ACCESS_SYSTEM_ADMIN_PERMISSION = "accounts.can_access_system_admin"


def get_explicit_permissions(user) -> list[str]:
    if isinstance(user, AnonymousUser) or not user.is_authenticated:
        return []

    direct_permissions = user.user_permissions.select_related("content_type")
    group_permissions = user.groups.prefetch_related("permissions__content_type").values_list(
        "permissions__content_type__app_label",
        "permissions__codename",
    )

    permissions = {
        f"{permission.content_type.app_label}.{permission.codename}"
        for permission in direct_permissions
    }
    permissions.update(
        f"{app_label}.{codename}"
        for app_label, codename in group_permissions
        if app_label and codename
    )
    return sorted(permissions)


def has_explicit_permission(user, permission_name: str) -> bool:
    return permission_name in get_explicit_permissions(user)
