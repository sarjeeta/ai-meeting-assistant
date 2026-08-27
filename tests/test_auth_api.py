"""
Integration tests for the auth flow, run against the real FastAPI app with
the Postgres dependency swapped for an in-memory SQLite DB (see conftest.py).
No real AWS/LLM/vector-store calls happen in any of these -- auth doesn't
touch those services.
"""

import pytest


@pytest.mark.asyncio
async def test_register_returns_token(client):
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "new-user@example.com", "password": "a-strong-password"},
    )
    assert response.status_code == 201
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_duplicate_email_returns_409(client):
    payload = {"email": "dupe@example.com", "password": "a-strong-password"}
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_register_rejects_short_password(client):
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "shortpass@example.com", "password": "short"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_with_correct_password_succeeds(client):
    payload = {"email": "logintest@example.com", "password": "correct-password"}
    await client.post("/api/v1/auth/register", json=payload)

    response = await client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.asyncio
async def test_login_with_wrong_password_returns_401(client):
    payload = {"email": "logintest2@example.com", "password": "correct-password"}
    await client.post("/api/v1/auth/register", json=payload)

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "logintest2@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_with_nonexistent_email_returns_401_not_404(client):
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "doesnotexist@example.com", "password": "whatever"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_rejects_missing_auth(client):
    response = await client.get("/api/v1/meetings")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_rejects_garbage_token(client):
    response = await client.get(
        "/api/v1/meetings", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_accepts_valid_token(client, auth_headers):
    response = await client.get("/api/v1/meetings", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []