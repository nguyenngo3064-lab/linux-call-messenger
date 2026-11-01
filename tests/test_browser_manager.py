import os
from pathlib import Path

from backend.browser.manager import BrowserManager


def test_browser_manager_starts_measures_and_stops_process_group(tmp_path, monkeypatch) -> None:
    executable = tmp_path / "fake-browser"
    executable.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then echo 'Test Browser 1.0'; exit 0; fi\n"
        "exec /bin/sleep 30\n"
    )
    executable.chmod(0o700)
    profile = tmp_path / "profile"
    monkeypatch.setenv("BROWSER_EXECUTABLE", str(executable))
    manager = BrowserManager(profile_dir=profile)

    started = manager.start()
    assert started["running"] is True
    assert started["version"] == "Test Browser 1.0"
    assert os.stat(profile).st_mode & 0o777 == 0o700

    stopped = manager.stop()
    assert stopped["running"] is False