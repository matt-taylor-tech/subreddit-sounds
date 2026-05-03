import bcrypt
from fastapi import Request


def hash_password(raw_password: str) -> str:
    return bcrypt.hashpw(raw_password.encode(), bcrypt.gensalt()).decode()


def verify_password(raw_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(raw_password.encode(), password_hash.encode())


def is_authenticated(request: Request) -> bool:
    return bool(request.session.get("is_authenticated"))
