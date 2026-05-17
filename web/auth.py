from datetime import datetime, timedelta

from fastapi import HTTPException, Request

try:
    import pam as _pam

    def pam_authenticate(username: str, password: str) -> bool:
        # Use a dedicated PAM service that skips shell validation so SFTP-only
        # users (shell=/usr/sbin/nologin) can authenticate alongside dev users.
        return _pam.pam().authenticate(username, password, service="zeropanel-web")
except ImportError:
    def pam_authenticate(username: str, password: str) -> bool:
        raise RuntimeError("python-pam is not installed")

from jose import JWTError, jwt

from web.config import JWT_SECRET, TOKEN_EXPIRY_HOURS

_ALGORITHM = "HS256"


def create_token(username: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS)
    return jwt.encode({"sub": username, "exp": expire}, JWT_SECRET, algorithm=_ALGORITHM)


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


async def get_current_user(request: Request) -> str:
    token = (
        request.cookies.get("access_token")
        or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    )
    if not token:
        raise HTTPException(401, "Not authenticated")
    username = decode_token(token)
    if not username:
        raise HTTPException(401, "Invalid or expired token")
    return username
