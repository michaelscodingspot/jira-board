# jira-board

Terminal UI for a Jira Cloud board, built with [Textual](https://textual.textualize.io/).
Issue list on the left, rendered issue (description and comments) on the right.

## Run

```sh
export JIRA_API_TOKEN=...      # Atlassian API token
uv run jira-board              # opens on the To Do column
uv run jira-board -s "in prog" # opens on a column (prefix match)
uv run jira-board -a           # opens on all but Done
```

Connection settings come from the jira-cli config file
`${JIRA_CONFIG_FILE:-~/.config/.jira/.config.yml}`: `server`, `login`, `board.id`, `board.name`.

## Keys

| Key | Action |
|---|---|
| `/` | search (instant filter on key, summary, status, labels) |
| `tab` | next pane: search → list → preview |
| `esc` | clear search / back to the list |
| `j` `k` `g` `G` | down, up, top, bottom |
| `h` `l` | previous / next column |
| `a` | switch To Do ↔ all but Done |
| `K` `J` | rank up / down one place |
| `T` `B` `M` | rank to top / bottom / middle of the column |
| `s` | change status |
| `L` | add or remove a label on the issue |
| `f` | label filter (include / exclude; `LowPriority` excluded by default) |
| `y` | type filter |
| `S` | sort: rank, newest created, newest updated, label |
| `d` | delete issue |
| `o` `enter` | open in browser |
| `w` | start work: pick agent, then the old `jira-board --start-work` claims a clone and opens a terminal |
| `r` | refresh from Jira |
| `?` | help |
| `q` | quit |

## How it works

- One fetch loads every issue that is not Done, in board rank order; switching columns filters that list locally. Done is fetched the first time you open it.
- Ranking moves the row at once and sends the rank change to Jira in the background; on failure the board reloads.
- Issues and previews are cached in `~/.cache/jira-board/cache.db`, so startup is instant and a preview is refetched only when the issue's `updated` time changes.
