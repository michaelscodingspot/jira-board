"""Connection settings: the jira-cli config file plus the JIRA_API_TOKEN environment variable.

The file is ${JIRA_CONFIG_FILE:-~/.config/.jira/.config.yml}. Only four values are read
(`server`, `login`, `board.id`, `board.name`), so a tiny line parser is enough and no YAML
library is needed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    server: str
    login: str
    token: str
    board_id: int
    board_name: str


def config_path() -> Path:
    return Path(os.environ.get("JIRA_CONFIG_FILE") or Path.home() / ".config" / ".jira" / ".config.yml")


def _scalar(value: str) -> str:
    return value.strip().strip("'\"")


def parse(text: str) -> dict[str, str]:
    """Top-level `key: value` pairs, plus `board.key` for keys nested one level under `board:`."""
    values: dict[str, str] = {}
    section = ""
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, _, value = line.strip().partition(":")
        if not line[0].isspace():
            section = key
            if value.strip():
                values[key] = _scalar(value)
        elif section == "board" and value.strip():
            values.setdefault(f"board.{key}", _scalar(value))
    return values


def load_config() -> Config:
    path = config_path()
    try:
        values = parse(path.read_text())
    except OSError as err:
        raise ConfigError(f"cannot read {path}: {err.strerror}") from err
    token = os.environ.get("JIRA_API_TOKEN", "")
    if not token:
        raise ConfigError("JIRA_API_TOKEN is not set")
    missing = [k for k in ("server", "login", "board.id") if not values.get(k)]
    if missing:
        raise ConfigError(f"{path} has no {', '.join(missing)}")
    try:
        board_id = int(values["board.id"])
    except ValueError as err:
        raise ConfigError(f"{path}: board.id is not a number") from err
    return Config(
        server=values["server"].rstrip("/"),
        login=values["login"],
        token=token,
        board_id=board_id,
        board_name=values.get("board.name", f"board {board_id}"),
    )
