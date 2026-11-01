# jira-board

Terminal UI for one Jira board (Python 3.13, Textual, run with `uv run jira-board`): issue list left, Markdown preview right. Port of the fzf script `/c/aut/InPathGitBash/jira-board`, with the look and keys of `/c/notion-tui`.

- `src/jira_board/app.py` — Textual app: column/all-but-Done views, search, filters, sort, rank, status, labels, delete, start work, key bindings.
- `src/jira_board/screens.py` — modal dialogs: confirm, pick one, multi pick (include/exclude), text input, help.
- `src/jira_board/jira.py` — async Jira REST client (httpx): agile board configuration/issues/rank, REST v3 issue, transitions, labels, delete.
- `src/jira_board/card.py` — issue JSON and ADF description/comments to Markdown for the preview; type and label emoji.
- `src/jira_board/cache.py` — SQLite cache `~/.cache/jira-board/cache.db` (`board`, `issues`, `issue_detail`) for instant startup and previews.
- `src/jira_board/config.py` — reads `~/.config/.jira/.config.yml` (jira-cli config: server, login, board id/name) and `JIRA_API_TOKEN`.
- `src/jira_board/desktop.py` — opens an issue in the browser with xdg-open.
- Start work (`w`) shells out to the old script: `jira-board --start-work KEY --agent X` (path in `JIRA_BOARD_LEGACY`). Clone claiming and terminal launch stay there.
- Jira calls run in background workers; UI never blocks. Linux only; no Windows.
