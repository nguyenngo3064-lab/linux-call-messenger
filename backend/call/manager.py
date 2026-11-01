"""Report only call state that can be verified reliably."""

from __future__ import annotations

from typing import Any


class CallManager:
    def status(self, browser_running: bool) -> dict[str, Any]:
        if not browser_running:
            return {
                "status": "unverified",
                "browser_running": False,
                "joined_at": None,
                "duration_seconds": None,
                "webrtc": "unavailable",
                "reason": "Trình duyệt chưa chạy; không thể xác minh phiên Messenger hoặc cuộc gọi.",
            }
        return {
            "status": "unverified",
            "browser_running": True,
            "joined_at": None,
            "duration_seconds": None,
            "webrtc": "unavailable",
            "reason": "Chưa có tín hiệu đáng tin cậy từ Messenger/WebRTC để xác nhận cuộc gọi.",
        }