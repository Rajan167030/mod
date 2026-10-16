from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Union
import bcrypt
from jose import jwt
from app.core.config import settings

# bcrypt only uses the first 72 bytes of a password; newer releases raise instead of truncating.
_BCRYPT_MAX_BYTES = 72


def _encode(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against the stored hash."""
    try:
        return bcrypt.checkpw(_encode(plain_password), hashed_password.encode("utf-8"))
    except ValueError:  # malformed or non-bcrypt hash
        return False


def get_password_hash(password: str) -> str:
    """Hash a password securely using bcrypt."""
    return bcrypt.hashpw(_encode(password), bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)).decode("utf-8")


def create_access_token(
    subject: Union[str, Any],
    role: str,
    expires_delta: Optional[timedelta] = None
) -> str:
    """Generate a signed JWT token containing subject and role claims."""
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "role": role,
        "type": "access_token"
    }
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt
