"""FastAPI entry point for the authenticated management API."""

from __future__ import annotations

import os
import secrets
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from backend.browser.manager import BrowserManager
from backend.call.manager import CallManager
from backend.core.logging import clear_file_logs, configure_file_logging, read_recent_file_logs
from backend.database.store import SQLiteStore
from backend.monitoring.service import SystemMonitor
from backend.monitoring.system import collect_system_metrics
from backend.security import hash_password, verify_password

_LOGIN_WINDOW_SECONDS = 900
_LOGIN_MAX_ATTEMPTS = 5


class LoginLimiter:
    _MAX_CLIENTS = 10_000

    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def is_limited(self, client: str, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        with self._lock:
            self._prune(current)
            attempts = self._attempts[client]
            while attempts and current - attempts[0] >= _LOGIN_WINDOW_SECONDS:
                attempts.popleft()
            return len(attempts) >= _LOGIN_MAX_ATTEMPTS

    def record_failure(self, client: str, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        with self._lock:
            self._prune(current)
            if client not in self._attempts and len(self._attempts) >= self._MAX_CLIENTS:
                self._attempts.pop(next(iter(self._attempts)))
            attempts = self._attempts[client]
            while attempts and current - attempts[0] >= _LOGIN_WINDOW_SECONDS:
                attempts.popleft()
            attempts.append(current)

    def clear(self, client: str) -> None:
        with self._lock:
            self._attempts.pop(client, None)

    def _prune(self, now: float) -> None:
        for address, attempts in list(self._attempts.items()):
            while attempts and now - attempts[0] >= _LOGIN_WINDOW_SECONDS:
                attempts.popleft()
            if not attempts:
                self._attempts.pop(address, None)


def create_app(
    admin_password_hash: str | None = None,
    session_secret: str | None = None,
    secure_cookie: bool | None = None,
    data_store: SQLiteStore | None = None,
) -> FastAPI:
    secret_key = session_secret or os.getenv("SESSION_SECRET_KEY") or secrets.token_urlsafe(48)
    cookie_https_only = (
        secure_cookie
        if secure_cookie is not None
        else os.getenv("SESSION_HTTPS_ONLY", "false").lower() == "true"
    )
    limiter = LoginLimiter()
    store = data_store or SQLiteStore()
    password_hash = store.initialize_admin_password_hash(
        admin_password_hash or os.getenv("ADMIN_PASSWORD_HASH")
    )
    initial_settings = store.get_settings()
    configure_file_logging(os.getenv("MCK_LOG_DIR"), initial_settings["log_size_mb"])
    browser_manager = BrowserManager(
        browser_name=initial_settings["browser_name"],
        auto_restart=initial_settings["browser_auto_restart"],
        check_interval=initial_settings["process_check_interval_seconds"],
    )
    call_manager = CallManager()
    system_monitor = SystemMonitor(store)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        browser_manager.start_monitor()
        system_monitor.start()
        if initial_settings["browser_auto_start"]:
            try:
                browser_manager.start()
            except RuntimeError as error:
                store.add_event("ERROR", "browser_start_failed", str(error))
        try:
            yield
        finally:
            browser_manager.stop_monitor()
            system_monitor.stop()
            browser_manager.stop()

    application = FastAPI(
        title="Messenger Call Keeper", docs_url=None, redoc_url=None, lifespan=lifespan
    )
    application.add_middleware(
        SessionMiddleware,
        secret_key=secret_key,
        session_cookie="mck_session",
        max_age=43_200,
        same_site="lax",
        https_only=cookie_https_only,
    )

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
    assets_dir = os.path.join(frontend_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    application.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @application.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(os.path.join(frontend_dir, "index.html"))

    def require_admin(request: Request) -> dict[str, Any]:
        session = request.session
        if (
            not session.get("admin_authenticated")
            or session.get("auth_epoch") != store.auth_epoch()
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Cần đăng nhập.")
        return session

    def require_csrf(
        session: dict[str, Any] = Depends(require_admin),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> None:
        expected = session.get("csrf_token")
        if not expected or not secrets.compare_digest(expected, csrf_token or ""):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token không hợp lệ.")

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/api/auth/login")
    async def login(request: Request) -> JSONResponse:
        current_password_hash = store.admin_password_hash()
        if not current_password_hash:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Chưa cấu hình ADMIN_PASSWORD_HASH.",
            )
        client = request.client.host if request.client else "unknown"
        if limiter.is_limited(client):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Thử lại sau 15 phút.")
        try:
            payload = await request.json()
        except (ValueError, UnicodeDecodeError):
            payload = {}
        password = payload.get("password") if isinstance(payload, dict) else None
        if (
            not isinstance(password, str)
            or len(password) > 1024
            or not verify_password(password, current_password_hash)
        ):
            limiter.record_failure(client)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Thông tin đăng nhập không hợp lệ.")
        limiter.clear(client)
        csrf_token = secrets.token_urlsafe(32)
        request.session.clear()
        request.session.update(
            {"admin_authenticated": True, "csrf_token": csrf_token, "auth_epoch": store.auth_epoch()}
        )
        return JSONResponse({"authenticated": True, "csrf_token": csrf_token})

    @application.get("/api/auth/status")
    def auth_status(session: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        return {"authenticated": True, "csrf_token": session["csrf_token"]}

    @application.post("/api/auth/logout", dependencies=[Depends(require_csrf)])
    def logout(request: Request) -> dict[str, bool]:
        request.session.clear()
        return {"authenticated": False}

    @application.post("/api/auth/change-password", dependencies=[Depends(require_csrf)])
    async def change_password(request: Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except (ValueError, UnicodeDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="Payload không hợp lệ.")
        current_password = payload.get("current_password")
        new_password = payload.get("new_password")
        current_hash = store.admin_password_hash()
        if (
            not isinstance(current_password, str)
            or len(current_password) > 1024
            or not current_hash
            or not verify_password(current_password, current_hash)
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Mật khẩu hiện tại không đúng.")
        if not isinstance(new_password, str) or len(new_password) > 1024:
            raise HTTPException(status_code=422, detail="Mật khẩu mới không hợp lệ.")
        try:
            new_hash = hash_password(new_password)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        epoch = store.change_admin_password_hash(new_hash)
        csrf_token = secrets.token_urlsafe(32)
        request.session.clear()
        request.session.update(
            {"admin_authenticated": True, "csrf_token": csrf_token, "auth_epoch": epoch}
        )
        store.add_event("INFO", "admin_password_changed", "Administrator password changed")
        return {"changed": True, "csrf_token": csrf_token}

    @application.get("/api/system", dependencies=[Depends(require_admin)])
    def system_metrics() -> dict[str, Any]:
        return collect_system_metrics()

    @application.get("/api/system/memory", dependencies=[Depends(require_admin)])
    def memory_metrics() -> dict[str, Any]:
        metrics = collect_system_metrics()
        return metrics["memory"] | {"swap": metrics["swap"]}

    @application.get("/api/system/cpu", dependencies=[Depends(require_admin)])
    def cpu_metrics() -> dict[str, Any]:
        return collect_system_metrics()["cpu"]

    @application.get("/api/system/history", dependencies=[Depends(require_admin)])
    def system_history(limit: int = 300) -> list[dict[str, Any]]:
        return store.recent_metrics(limit)

    @application.get("/api/browser/status", dependencies=[Depends(require_admin)])
    def browser_status() -> dict[str, Any]:
        return browser_manager.status()

    @application.post("/api/browser/start", dependencies=[Depends(require_csrf)])
    def browser_start() -> dict[str, Any]:
        try:
            return browser_manager.start()
        except RuntimeError as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error

    @application.post("/api/browser/stop", dependencies=[Depends(require_csrf)])
    def browser_stop() -> dict[str, Any]:
        return browser_manager.stop()

    @application.get("/api/call/status", dependencies=[Depends(require_admin)])
    def call_status() -> dict[str, Any]:
        return call_manager.status(browser_manager.status()["running"])

    @application.get("/api/logs", dependencies=[Depends(require_admin)])
    def logs(limit: int = 100) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(limit, 500))
        combined = store.recent_events(bounded_limit) + read_recent_file_logs(bounded_limit)
        return sorted(combined, key=lambda event: event["created_at"], reverse=True)[:bounded_limit]

    @application.delete("/api/logs", dependencies=[Depends(require_csrf)])
    def clear_logs() -> dict[str, int]:
        return {"deleted": store.clear_events() + clear_file_logs()}

    @application.get("/api/settings", dependencies=[Depends(require_admin)])
    def get_settings() -> dict[str, Any]:
        return store.get_settings()

    @application.put("/api/settings", dependencies=[Depends(require_csrf)])
    async def update_settings(request: Request) -> dict[str, Any]:
        try:
            updates = await request.json()
            if not isinstance(updates, dict):
                raise ValueError("Thiết lập phải là một object JSON.")
            candidate = store.validate_settings(updates)
            browser_manager.configure(
                candidate["browser_name"],
                candidate["browser_auto_restart"],
                candidate["process_check_interval_seconds"],
            )
            updated = store.update_settings(updates)
            configure_file_logging(os.getenv("MCK_LOG_DIR"), updated["log_size_mb"])
            return updated
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @application.get("/api/diagnostics", dependencies=[Depends(require_admin)])
    def diagnostics() -> dict[str, Any]:
        return {
            "system": collect_system_metrics(),
            "browser": browser_manager.status(),
            "call": call_manager.status(browser_manager.status()["running"]),
            "settings": store.get_settings(),
            "recent_events": logs(100),
        }

    return application


app = create_app()