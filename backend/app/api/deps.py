from typing import Generator, List, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.permissions import UserRole, has_required_role
from app.core.errors import PermissionDeniedError
from app.db.session import get_db
from app.models.all_models import User

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/login",
    auto_error=False
)


def get_current_user(
    db: Session = Depends(get_db),
    token: Optional[str] = Depends(oauth2_scheme)
) -> User:
    """Validate bearer token and return the authenticated User model."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not token:
        # Opt-in only: treat unauthenticated requests as the demo admin (never enable outside local dev)
        if settings.AUTH_DEV_BYPASS:
            default_user = db.query(User).filter_by(role=UserRole.ADMIN.value).first()
            if default_user:
                return default_user
        raise credentials_exception

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")

    return user


def require_roles(*allowed_roles: UserRole):
    """Factory dependency enforcing RBAC on endpoints."""
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if not has_required_role(current_user.role, list(allowed_roles)):
            raise PermissionDeniedError(action=f"access this resource. Required roles: {[r.value for r in allowed_roles]}")
        return current_user
    return role_checker
