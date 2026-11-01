from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.database.store import SQLiteStore
from backend.security import hash_password


class FormNestingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.form_depth = 0
        self.nested_form = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "form":
            self.nested_form |= self.form_depth > 0
            self.form_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self.form_depth = max(0, self.form_depth - 1)


def make_client(database_path) -> TestClient:
    return TestClient(
        create_app(
            admin_password_hash=hash_password("correct horse battery"),
            session_secret="test-secret-key-that-is-long-enough",
            secure_cookie=False,
            data_store=SQLiteStore(database_path),
        )
    )


def test_system_metrics_require_admin_login(tmp_path) -> None:
    client = make_client(tmp_path / "system.sqlite3")
    assert client.get("/api/system").status_code == 401
    response = client.post("/api/auth/login", json={"password": "correct horse battery"})
    assert response.status_code == 200
    assert client.get("/api/system").status_code == 200


def test_login_rate_limit_and_csrf_protected_logout(tmp_path) -> None:
    client = make_client(tmp_path / "auth.sqlite3")
    for _ in range(5):
        assert client.post("/api/auth/login", json={"password": "wrong password"}).status_code == 401
    assert client.post("/api/auth/login", json={"password": "correct horse battery"}).status_code == 429

    client = make_client(tmp_path / "logout.sqlite3")
    login_response = client.post("/api/auth/login", json={"password": "correct horse battery"})
    csrf_token = login_response.json()["csrf_token"]
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token}).status_code == 200
    assert client.get("/api/system").status_code == 401


def test_system_metrics_report_measured_values(tmp_path) -> None:
    client = make_client(tmp_path / "metrics.sqlite3")
    client.post("/api/auth/login", json={"password": "correct horse battery"})
    response = client.get("/api/system")
    assert response.status_code == 200
    payload = response.json()
    assert payload["cpu"]["cores_logical"] >= 1
    assert payload["memory"]["total_bytes"] > 0
    assert payload["disk"]["total_bytes"] > 0


def test_call_state_is_never_reported_as_connected_without_verification(tmp_path) -> None:
    client = make_client(tmp_path / "call.sqlite3")
    client.post("/api/auth/login", json={"password": "correct horse battery"})
    response = client.get("/api/call/status")
    assert response.status_code == 200
    assert response.json()["status"] == "unverified"
    assert response.json()["webrtc"] == "unavailable"


def test_browser_control_requires_csrf_token(tmp_path) -> None:
    client = make_client(tmp_path / "browser.sqlite3")
    client.post("/api/auth/login", json={"password": "correct horse battery"})
    assert client.post("/api/browser/start").status_code == 403


def test_settings_logs_and_static_dashboard_are_protected_and_served(tmp_path) -> None:
    client = make_client(tmp_path / "dashboard.sqlite3")
    assert client.get("/").status_code == 200
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/api/settings").status_code == 401
    login_response = client.post("/api/auth/login", json={"password": "correct horse battery"})
    csrf_token = login_response.json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf_token}
    response = client.put("/api/settings", json={"mode": "balanced"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["mode"] == "balanced"
    invalid = client.put("/api/settings", json={"mode": "shell"}, headers=headers)
    assert invalid.status_code == 422
    assert client.get("/api/logs").status_code == 200
    assert client.get("/api/system/history").status_code == 200


def test_password_change_invalidates_old_sessions(tmp_path) -> None:
    database_path = tmp_path / "password.sqlite3"
    first_client = make_client(database_path)
    second_client = make_client(database_path)
    first_login = first_client.post("/api/auth/login", json={"password": "correct horse battery"})
    second_client.post("/api/auth/login", json={"password": "correct horse battery"})
    response = first_client.post(
        "/api/auth/change-password",
        json={"current_password": "correct horse battery", "new_password": "new secure password"},
        headers={"X-CSRF-Token": first_login.json()["csrf_token"]},
    )
    assert response.status_code == 200
    assert first_client.get("/api/system").status_code == 200
    assert second_client.get("/api/system").status_code == 401
    assert first_client.post("/api/auth/login", json={"password": "correct horse battery"}).status_code == 401
    assert first_client.post("/api/auth/login", json={"password": "new secure password"}).status_code == 200


def test_dashboard_forms_are_not_nested() -> None:
    parser = FormNestingParser()
    parser.feed((Path(__file__).parent.parent / "frontend" / "index.html").read_text())
    assert not parser.nested_form
    assert parser.form_depth == 0