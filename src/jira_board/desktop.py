"""Open a URL in the default browser without blocking or printing over the TUI."""

from __future__ import annotations

import subprocess
import webbrowser


def open_url(url: str) -> None:
    try:
        subprocess.Popen(
            ["xdg-open", url],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError:
        webbrowser.open(url)
