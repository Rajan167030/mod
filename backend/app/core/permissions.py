from enum import Enum
from typing import List


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    PLANNER = "PLANNER"
    REVIEWER = "REVIEWER"
    VIEWER = "VIEWER"


# Permission matrices
ROLE_HIERARCHY = {
    UserRole.ADMIN: [UserRole.ADMIN, UserRole.PLANNER, UserRole.REVIEWER, UserRole.VIEWER],
    UserRole.PLANNER: [UserRole.PLANNER, UserRole.VIEWER],
    UserRole.REVIEWER: [UserRole.REVIEWER, UserRole.VIEWER],
    UserRole.VIEWER: [UserRole.VIEWER],
}


def has_required_role(user_role: str, allowed_roles: List[UserRole]) -> bool:
    """Check if the user's role satisfies any of the allowed roles."""
    try:
        current_role = UserRole(user_role)
    except ValueError:
        return False
    return any(allowed in ROLE_HIERARCHY.get(current_role, []) for allowed in allowed_roles)
