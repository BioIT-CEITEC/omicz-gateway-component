from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from core.security import decode_access_token, InvalidToken
from db.session import get_db
from db.repositories.users import get_by_uuid
from db.models.users import Users


def require_user(request: Request, db: Session = Depends(get_db)) -> Users:
    """The logged-in user from 'Authorization: Bearer <access token>'; 401 otherwise."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not logged in",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = decode_access_token(auth[len("Bearer "):])
    except InvalidToken as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {e}",
                            headers={"WWW-Authenticate": "Bearer"})
    user = get_by_uuid(claims["sub"], db)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account disabled",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


def require_admin(user: Users = Depends(require_user)) -> Users:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrators only")
    return user
