"""Shared helpers for granting/querying a user's submodule permissions."""
from __future__ import annotations

from apps.platform.modules.models import (
    Submodule,
    SubmodulePermission,
    TenantModule,
    UserSubmodulePermission,
)


def grant_all_tenant_module_permissions(user) -> None:
    """
    Grant ``user`` every submodule permission available under the modules
    assigned to their tenant. Idempotent — skips permissions the user
    already holds instead of duplicating rows.
    """
    if not user.tenant_id:
        return

    module_ids = TenantModule.objects.filter(
        tenant_id=user.tenant_id
    ).values_list("module_id", flat=True)

    submodule_ids = Submodule.objects.filter(
        module_id__in=module_ids, is_archived=False
    ).values_list("id", flat=True)

    submodule_permission_ids = set(
        SubmodulePermission.objects.filter(
            submodule_id__in=submodule_ids
        ).values_list("id", flat=True)
    )

    already_granted = set(
        UserSubmodulePermission.objects.filter(
            user=user, submodule_permission_id__in=submodule_permission_ids
        ).values_list("submodule_permission_id", flat=True)
    )

    to_create = submodule_permission_ids - already_granted
    UserSubmodulePermission.objects.bulk_create([
        UserSubmodulePermission(
            user=user,
            tenant_id=user.tenant_id,
            submodule_permission_id=spid,
        )
        for spid in to_create
    ])


def sync_user_submodule_permissions(user, submodule_permission_ids) -> None:
    """
    Replace ``user``'s granted submodule permissions with exactly
    ``submodule_permission_ids`` (removes anything not in the list, adds
    anything missing). Used when an admin explicitly selects a user's
    permission set, as opposed to the blanket grant-all above.
    """
    UserSubmodulePermission.objects.filter(user=user).delete()
    UserSubmodulePermission.objects.bulk_create([
        UserSubmodulePermission(
            user=user,
            tenant_id=user.tenant_id,
            submodule_permission_id=spid,
        )
        for spid in submodule_permission_ids
    ])
