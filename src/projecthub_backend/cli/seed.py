from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session

from projecthub_backend.core.database import SessionalLocal
from projecthub_backend.models.billing import Plan
from projecthub_backend.models.workspace import Permission, RolePermission, WorkspaceRole


SYSTEM_ROLES = [
    {"name": "Owner", "description": "Full administrative access to workspace, billing, and members."},
    {"name": "Admin", "description": "Can manage projects, tasks, and workspace members."},
    {"name": "Member", "description": "Can view workspace projects and create/update assigned tasks."},
]

PERMISSIONS = [
    {"name": "manage_workspace", "description": "Update workspace settings or delete workspace"},
    {"name": "manage_billing", "description": "View and manage workspace subscriptions and billing"},
    {"name": "manage_roles", "description": "Create or modify custom workspace roles"},
    {"name": "invite_member", "description": "Invite new members and manage workspace memberships"},
    {"name": "create_project", "description": "Create new projects inside the workspace"},
    {"name": "delete_project", "description": "Archive or delete existing projects"},
    {"name": "manage_tasks", "description": "Create, assign, update, and delete tasks"},
]

ROLE_PERMISSION_MAP: dict[str, list[str]] = {
    "Owner": [
        "manage_workspace",
        "manage_billing",
        "manage_roles",
        "invite_member",
        "create_project",
        "delete_project",
        "manage_tasks",
    ],
    "Admin": [
        "invite_member",
        "create_project",
        "delete_project",
        "manage_tasks",
    ],
    "Member": [
        "manage_tasks",
    ],
}

DEFAULT_PLANS = [
    {
        "name": "Free",
        "description": "Essential project and task management for small teams.",
        "price": Decimal("0.00"),
        "billing_interval": "monthly",
        "max_members": 5,
        "max_projects": 3,
        "features": {"kanban": True, "chat": True, "file_storage_mb": 500},
        "is_active": True,
    },
    {
        "name": "Pro",
        "description": "Unlimited projects and advanced collaboration for growing teams.",
        "price": Decimal("15.00"),
        "billing_interval": "monthly",
        "max_members": 25,
        "max_projects": None,
        "features": {"kanban": True, "chat": True, "file_storage_mb": 10240, "activity_logs": True},
        "is_active": True,
    },
    {
        "name": "Enterprise",
        "description": "Custom roles, unlimited scale, and priority support.",
        "price": Decimal("49.00"),
        "billing_interval": "monthly",
        "max_members": None,
        "max_projects": None,
        "features": {"kanban": True, "chat": True, "file_storage_mb": 102400, "activity_logs": True, "custom_roles": True},
        "is_active": True,
    },
]


def seed_roles_and_permissions(db: Session) -> None:
    # 1. Seed Permissions
    perm_by_name: dict[str, Permission] = {}
    for item in PERMISSIONS:
        perm = db.scalar(select(Permission).where(Permission.name == item["name"]))
        if not perm:
            perm = Permission(name=item["name"], description=item["description"])
            db.add(perm)
            db.flush()
        perm_by_name[perm.name] = perm

    # 2. Seed System Roles (workspace_id = None, is_system_role = True)
    role_by_name: dict[str, WorkspaceRole] = {}
    for item in SYSTEM_ROLES:
        role = db.scalar(
            select(WorkspaceRole).where(
                WorkspaceRole.name == item["name"],
                WorkspaceRole.is_system_role.is_(True),
                WorkspaceRole.workspace_id.is_(None),
            )
        )
        if not role:
            role = WorkspaceRole(
                workspace_id=None,
                name=item["name"],
                description=item["description"],
                is_system_role=True,
            )
            db.add(role)
            db.flush()
        role_by_name[role.name] = role

    # 3. Seed Role -> Permission mappings
    for role_name, perm_names in ROLE_PERMISSION_MAP.items():
        role = role_by_name[role_name]
        for perm_name in perm_names:
            perm = perm_by_name[perm_name]
            exists = db.scalar(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == perm.id,
                )
            )
            if not exists:
                db.add(RolePermission(role_id=role.id, permission_id=perm.id))


def seed_plans(db: Session) -> None:
    for item in DEFAULT_PLANS:
        plan = db.scalar(select(Plan).where(Plan.name == item["name"]))
        if not plan:
            db.add(Plan(**item))


def run_seed() -> None:
    print("Seeding ProjectHub database...")
    db = SessionalLocal()
    try:
        seed_roles_and_permissions(db)
        seed_plans(db)
        db.commit()
        print("Database seeded successfully!")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
