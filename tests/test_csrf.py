"""CSRF protection: verify_csrf dependency + token round-trip via the session."""

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from app.csrf import ensure_token, verify_csrf


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")

    @app.get("/token")
    def token(request: Request):
        return {"csrf_token": ensure_token(request)}

    @app.post("/do", dependencies=[Depends(verify_csrf)])
    def do():
        return {"ok": True}

    return TestClient(app)


def test_post_without_token_rejected():
    r = _client().post("/do", data={})
    assert r.status_code == 403


def test_post_with_valid_token_accepted():
    client = _client()
    tok = client.get("/token").json()["csrf_token"]  # also sets the session cookie
    r = client.post("/do", data={"csrf_token": tok})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_post_with_wrong_token_rejected():
    client = _client()
    client.get("/token")  # establish a session token
    r = client.post("/do", data={"csrf_token": "not-the-real-token"})
    assert r.status_code == 403
