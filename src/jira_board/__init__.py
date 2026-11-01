"""jira-board: a Textual UI for one Jira board."""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="jira-board", description="Terminal UI for a Jira board.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-s", "--status", metavar="COLUMN", help="open on this column (case-insensitive prefix)")
    group.add_argument("-a", "--all", action="store_true", help="open on the all-but-Done list")
    args = parser.parse_args()

    from .config import ConfigError, load_config

    try:
        config = load_config()
    except ConfigError as err:
        sys.exit(f"jira-board: {err}")

    from .app import JiraBoard

    JiraBoard(config, start_column=args.status, start_all=args.all).run()
