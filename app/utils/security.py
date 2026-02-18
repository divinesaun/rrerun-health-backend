from datetime import datetime, timedelta
from typing import Optional, Dict

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from app.config import settings
from app import database as db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/pharmacy/auth/login")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(data: Dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.JWT_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_jwt(token: str) -> Dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(token: str = Depends(oauth2_scheme)) -> Dict:
    """Dependency: returns the current pharmacy user from JWT."""
    payload = decode_jwt(token)
    if payload.get("role") == "admin":
        raise HTTPException(status_code=403, detail="Admin tokens cannot access pharmacy endpoints")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    user = await db.get_pharmacy_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def require_admin(token: str = Depends(oauth2_scheme)) -> Dict:
    """Dependency: ensures the caller is an admin. Rejects pharmacy JWTs."""
    payload = decode_jwt(token)
    role = payload.get("role")
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    admin_id = payload.get("sub")
    admin = await db.get_admin_by_email(admin_id)
    if not admin:
        raise HTTPException(status_code=403, detail="Admin account not found")
    return admin
