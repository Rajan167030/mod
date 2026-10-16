from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.all_models import User
from app.core.security import verify_password, create_access_token
from app.api.deps import get_current_user
from app.services.audit_service import log_audit_event
from app.schemas.all_schemas import LoginRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate user credentials and issue signed JWT token."""
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        log_audit_event(
            db,
            action="LOGIN_FAILED",
            entity_type="USER",
            metadata={"email": payload.email, "reason": "Invalid credentials"}
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user account")

    access_token = create_access_token(subject=user.id, role=user.role)

    log_audit_event(
        db,
        action="LOGIN_SUCCESS",
        entity_type="USER",
        entity_id=user.id,
        actor=user,
        metadata={"email": user.email, "role": user.role}
    )
    db.commit()

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=user.id,
        email=user.email,
        role=user.role
    )


@router.get("/me", response_model=UserResponse)
def get_current_user_profile(current_user: User = Depends(get_current_user)):
    """Return the profile of the currently authenticated user."""
    return current_user


@router.post("/logout")
def logout(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Log out current user and record audit event."""
    log_audit_event(
        db,
        action="LOGOUT",
        entity_type="USER",
        entity_id=current_user.id,
        actor=current_user
    )
    db.commit()
    return {"message": "Logged out successfully"}
