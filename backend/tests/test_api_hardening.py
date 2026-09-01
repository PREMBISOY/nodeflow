from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app, resolve_frontend_file


def test_http_exceptions_use_the_documented_error_envelope():
    client = TestClient(create_app(load_demo_data=False))

    response = client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.json() == {
        "success": False,
        "data": None,
        "error": {
            "code": "AUTHENTICATION_REQUIRED",
            "message": "Authentication required",
        },
    }
    assert response.headers["X-Request-ID"]


def test_validation_errors_include_the_invalid_field():
    client = TestClient(create_app())

    response = client.post("/api/v1/events", json={"event_type": "test"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "project_id" in response.json()["error"]["message"]


def test_frontend_file_resolution_cannot_escape_the_static_root():
    static = Path(__file__).resolve().parent
    asset = Path(__file__).resolve()

    assert resolve_frontend_file(static, asset.name) == asset
    assert resolve_frontend_file(static, "../app/main.py") is None


def test_liveness_and_readiness_are_distinct_and_enveloped():
    client = TestClient(create_app(load_demo_data=False))

    live = client.get("/health/live")
    ready = client.get("/health/ready")

    assert live.json()["data"]["status"] == "alive"
    assert ready.json()["data"] == {"status": "ready", "database": "in-memory"}


def test_unexpected_errors_are_logged_but_not_exposed():
    app = create_app(load_demo_data=False)

    @app.get("/test-only/boom")
    def boom():
        raise RuntimeError("sensitive internal detail")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/test-only/boom")

    assert response.status_code == 500
    assert response.json() == {
        "success": False,
        "data": None,
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred",
        },
    }
    assert "sensitive internal detail" not in response.text
    assert response.headers["X-Request-ID"]
