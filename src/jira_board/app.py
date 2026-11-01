"""Issue list on the left, Markdown preview on the right — notion-tui's layout and keys, for a Jira board."""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import replace

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.timer import Timer
from textual.widgets import Footer, Input, Label, ListItem, ListView, Markdown, Static

from . import desktop
from .cache import Cache
from .card import card_markdown, label_emoji, type_emoji
from .config import Config
from .jira import Column, Issue, Jira, JiraError
from .screens import ConfirmScreen, HelpScreen, InputScreen, MultiPickScreen, PickScreen

PREVIEW_DEBOUNCE = 0.12  # seconds to wait after the cursor stops before loading a preview
BUILTIN_LABELS = ["Blog", "LowPriority", "ScanAutoBug", "Validation", "open-source"]
DEFAULT_EXCLUDE = {"LowPriority"}
SORTS = [("rank", "Rank — board order"), ("created", "Newest created"), ("updated", "Newest updated"), ("label", "Label A-Z")]
AGENTS = [("claude", "Claude Code"), ("codex", "Codex"), ("gemini", "Gemini")]
LEGACY_BOARD = os.environ.get("JIRA_BOARD_LEGACY", "/c/aut/InPathGitBash/jira-board")
_LABEL_JUNK = re.compile(r"[\s,()]")


class IssueItem(ListItem):
    def __init__(self, issue: Issue, show_status: bool) -> None:
        super().__init__()
        self.issue = issue
        self.show_status = show_status

    def compose(self) -> ComposeResult:
        i = self.issue
        text = Text(no_wrap=True)
        text.append(f"{i.key:<8} ", style="bold")
        if self.show_status:  # before the emoji, so it lines up
            text.append(f"{i.status_name[:13]:<13} ", style="italic")
        text.append(type_emoji(i.type))
        for label in i.labels:
            text.append(label_emoji(label))
        if i.comments:
            text.append(f" 💬{i.comments}", style="dim")
        text.append(" ")
        text.append(i.summary)
        yield Label(text, classes="title")


class IssueList(ListView):
    BINDINGS = [
        Binding("j", "cursor_down", "down", show=False),
        Binding("k", "cursor_up", "up", show=False),
        Binding("g", "first", "top", show=False),
        Binding("G", "last", "bottom", show=False),
    ]

    def action_first(self) -> None:
        if self.children:
            self.index = 0

    def action_last(self) -> None:
        if self.children:
            self.index = len(self.children) - 1


class PreviewScroll(VerticalScroll, can_focus=True):
    BINDINGS = [
        Binding("j", "scroll_down", "down", show=False),
        Binding("k", "scroll_up", "up", show=False),
        Binding("space", "page_down", "page down", show=False),
        Binding("g", "scroll_home", "top", show=False),
        Binding("G", "scroll_end", "bottom", show=False),
    ]


class JiraBoard(App):
    TITLE = "jira-board"
    CSS = """
    #topbar { height: 1; margin: 0 1; }
    #search { width: 1fr; height: 1; border: none; padding: 0 1; background: $surface; }
    #search:focus { background: $boost; }
    #status { width: auto; padding-left: 2; color: $text-muted; }
    #body { height: 1fr; }
    #list-pane { width: 1fr; max-width: 90; border: round $border-blurred; border-title-color: $text-muted; }
    #list-pane:focus-within { border: round $accent; border-title-color: $accent; }
    #preview-pane { width: 1fr; border: round $border-blurred; border-title-color: $text-muted; border-subtitle-color: $text-muted; }
    #preview-pane:focus-within { border: round $accent; border-title-color: $accent; }
    PreviewScroll { padding: 0 1; }
    IssueList { background: transparent; scrollbar-size-vertical: 1; }
    IssueItem { height: 1; padding: 0 1; }
    IssueList > IssueItem.-highlight { background: $block-cursor-blurred-background; }
    IssueList:focus > IssueItem.-highlight { background: $accent; color: $background; text-style: bold; }
    IssueItem .title { width: 1fr; text-wrap: nowrap; text-overflow: ellipsis; }
    #preview { background: transparent; }
    """

    BINDINGS = [
        Binding("slash", "focus_search", "search"),
        Binding("h,alt+left", "column(-1)", "◀ col"),
        Binding("l,alt+right", "column(1)", "col ▶"),
        Binding("a", "toggle_all", "all/To Do"),
        Binding("K,alt+up", "rank('up')", "rank up", show=False),
        Binding("J,alt+down", "rank('down')", "rank down", show=False),
        Binding("T", "rank('top')", "rank top", show=False),
        Binding("B", "rank('bottom')", "rank bottom", show=False),
        Binding("M", "rank('middle')", "rank middle", show=False),
        Binding("s", "status", "status"),
        Binding("L", "set_label", "label"),
        Binding("f", "label_filter", "filter"),
        Binding("y", "type_filter", "type", show=False),
        Binding("S", "sort", "sort", show=False),
        Binding("d", "delete", "delete", show=False),
        Binding("o", "browser", "open"),
        Binding("w", "start_work", "work"),
        Binding("r", "refresh", "refresh"),
        Binding("escape", "back", "back", show=False),
        Binding("question_mark", "help", "help"),
        Binding("q", "quit", "quit"),
    ]

    def __init__(
        self,
        config: Config,
        jira: Jira | None = None,
        cache: Cache | None = None,
        start_column: str | None = None,
        start_all: bool = False,
    ) -> None:
        super().__init__()
        self.config = config
        self.jira = jira or Jira(config)
        self.cache = cache or Cache()
        self.board_name = config.board_name
        self.columns: list[Column] = []
        self.status_col: dict[str, int] = {}  # status id -> column index
        self.todo_col = 0
        self.done_col = 0
        self.issues: list[Issue] = []  # every known issue on the board, in rank order
        self.shown: list[Issue] = []  # issues in the list right now, in order
        self.current: Issue | None = None
        self.show_all = start_all  # True: all but Done; False: one column
        self.col = 0
        self.include: set[str] = set()
        self.exclude: set[str] = set(DEFAULT_EXCLUDE)
        self.types: set[str] = set()
        self.sort = "rank"
        self.query_text = ""
        self.message = ""  # last action result, shown in the status line
        self._start_column = start_column
        self._done_loaded = False
        self._loading = 0
        self._rendered_key: str | None = None
        self._preview_timer: Timer | None = None
        self._rank_lock = asyncio.Lock()

    # ---------- layout ----------

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Input(placeholder="/ search issues…", id="search")
            yield Static("", id="status")
        with Horizontal(id="body"):
            with Vertical(id="list-pane"):
                yield IssueList(id="issues")
            with Vertical(id="preview-pane"):
                with PreviewScroll():
                    yield Markdown("", id="preview")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one(IssueList).focus()
        cached = self.cache.board(self.config.board_id)
        if cached:
            self._set_board(*cached)
            self.issues = self.cache.issues(self.config.board_id)
            await self._render_list()
        self.load_board()

    # ---------- board and columns ----------

    def _set_board(self, name: str, columns: list[Column]) -> None:
        old = self.columns[self.col].name if self.columns else None
        self.board_name = name
        self.columns = columns
        self.status_col = {sid: n for n, c in enumerate(columns) for sid in c.status_ids}
        names = [c.name.lower() for c in columns]
        self.todo_col = next((n for n, c in enumerate(names) if re.match(r"^to[ _-]*do", c)), 0)
        self.done_col = next((n for n, c in enumerate(names) if c.startswith("done")), len(columns) - 1)
        if self._start_column is not None:
            want = self._start_column.lower()
            self._start_column = None
            match = next((n for n, c in enumerate(names) if c.startswith(want)), None)
            if match is None:
                self.notify(f"No column “{want}”. Columns: {', '.join(c.name for c in columns)}", severity="error")
                self.col = self.todo_col
            else:
                self.col = match
        elif old is not None and old.lower() in names:
            self.col = names.index(old.lower())
        else:
            self.col = self.todo_col

    @property
    def done_ids(self) -> tuple[str, ...]:
        return self.columns[self.done_col].status_ids if self.columns else ()

    def _col_of(self, issue: Issue) -> int:
        return self.status_col.get(issue.status_id, len(self.columns))

    def _in_done(self, issue: Issue) -> bool:
        return issue.status_id in self.done_ids

    def _viewing_done(self) -> bool:
        return bool(self.columns) and not self.show_all and self.col == self.done_col

    def _jql(self, done: bool) -> str:
        ids = ",".join(self.done_ids)
        if done:
            return f"status in ({ids}) ORDER BY Rank ASC"
        return f"status not in ({ids}) ORDER BY Rank ASC" if ids else "ORDER BY Rank ASC"

    @work(exclusive=True, group="list")
    async def load_board(self) -> None:
        """Fetch the board layout and its issues (Done only when it is on screen)."""
        self._loading += 1
        self._update_status()
        try:
            name, columns = await self.jira.board()
            self.cache.put_board(self.config.board_id, name, columns)
            self._set_board(name, columns)
            fresh = await self.jira.board_issues(self._jql(done=False))
            keys = {i.key for i in fresh}
            done = [i for i in self.issues if self._in_done(i) and i.key not in keys]
            if self._viewing_done():
                done = await self.jira.board_issues(self._jql(done=True))
                self._done_loaded = True
            self._store(fresh + done)
        except JiraError as err:
            self.notify(str(err), title="Jira fetch failed", severity="error", timeout=10)
            return
        finally:
            self._loading -= 1
            self._update_status()
        await self._render_list(keep_key=self._current_key())

    @work(exclusive=True, group="done")
    async def load_done(self) -> None:
        self._loading += 1
        self._update_status()
        try:
            done = await self.jira.board_issues(self._jql(done=True))
        except JiraError as err:
            self.notify(str(err), title="Jira fetch failed", severity="error", timeout=10)
            return
        finally:
            self._loading -= 1
            self._update_status()
        self._done_loaded = True
        keys = {i.key for i in done}
        self._store([i for i in self.issues if not self._in_done(i) and i.key not in keys] + done)
        if self._viewing_done():
            await self._render_list(keep_key=self._current_key())

    def _store(self, issues: list[Issue]) -> None:
        self.issues = issues
        self.cache.save_issues(self.config.board_id, issues)

    def _current_key(self) -> str | None:
        return self.current.key if self.current else None

    # ---------- list ----------

    def _scope(self) -> list[Issue]:
        if not self.columns:
            return list(self.issues)
        if self.show_all:
            rest = [i for i in self.issues if not self._in_done(i)]
            return sorted(rest, key=self._col_of)  # stable: rank order kept inside each column
        ids = set(self.columns[self.col].status_ids)
        return [i for i in self.issues if i.status_id in ids]

    def _visible(self) -> list[Issue]:
        issues = self._scope()
        if self.types:
            issues = [i for i in issues if i.type in self.types]
        if self.exclude:
            issues = [i for i in issues if not self.exclude.intersection(i.labels)]
        if self.include:
            issues = [i for i in issues if self.include.intersection(i.labels)]
        if self.query_text:
            needle = self.query_text.lower()
            issues = [i for i in issues if needle in f"{i.key} {i.summary} {i.status_name} {' '.join(i.labels)}".lower()]
        if self.sort == "created":
            issues.sort(key=lambda i: i.created, reverse=True)
        elif self.sort == "updated":
            issues.sort(key=lambda i: i.updated, reverse=True)
        elif self.sort == "label":
            issues.sort(key=lambda i: (not i.labels, i.labels[0].lower() if i.labels else ""))
        return issues

    def _view_name(self) -> str:
        if self.show_all:
            return "All but Done"
        return self.columns[self.col].name if self.columns else "…"

    def _update_status(self) -> None:
        parts = [self.board_name, f"{len(self.shown)} issues"]
        if self.include:
            parts.append("label " + ", ".join(sorted(self.include)))
        if self.exclude:
            parts.append("without " + ", ".join(sorted(self.exclude)))
        if self.types:
            parts.append("type " + ", ".join(sorted(self.types)))
        if self.sort != "rank":
            parts.append("sort " + self.sort)
        if self.message:
            parts.append(self.message)
        if self._loading:
            parts.append("loading…")
        self.query_one("#status", Static).update(" · ".join(parts))
        if self.columns and not self.show_all:
            position = f" {self.col + 1}/{len(self.columns)}"
        else:
            position = ""
        self.query_one("#list-pane").border_title = self._view_name() + position

    async def _render_list(self, keep_key: str | None = None, fallback_index: int = 0) -> None:
        list_view = self.query_one(IssueList)
        issues = self.shown = self._visible()
        await list_view.clear()
        await list_view.extend(IssueItem(i, self.show_all) for i in issues)
        if issues:
            keys = [i.key for i in issues]
            list_view.index = keys.index(keep_key) if keep_key in keys else min(fallback_index, len(issues) - 1)
        else:
            self.current = None
            await self._render_message("No issues." if not self._loading else "loading…")
        self._update_status()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if not isinstance(event.item, IssueItem):
            return
        self.current = event.item.issue
        if self._preview_timer:
            self._preview_timer.stop()
        self._preview_timer = self.set_timer(PREVIEW_DEBOUNCE, self._show_current)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.action_browser()

    # ---------- search ----------

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "search":
            return
        self.query_text = event.value.strip()
        await self._render_list(keep_key=self._current_key())

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            self.query_one(IssueList).focus()

    # ---------- preview ----------

    async def _render_message(self, text: str) -> None:
        self._rendered_key = None
        pane = self.query_one("#preview-pane")
        pane.border_title = ""
        pane.border_subtitle = ""
        await self.query_one("#preview", Markdown).update(f"_{text}_")

    async def _render_card(self, key: str, data: dict | None, note: str = "") -> None:
        pane = self.query_one("#preview-pane")
        pane.border_title = key
        pane.border_subtitle = note
        content = card_markdown(data, self.config.server) if data else "_loading…_"
        await self.query_one("#preview", Markdown).update(content)
        if self._rendered_key != key:
            self.query_one(PreviewScroll).scroll_home(animate=False)
            self._rendered_key = key

    async def _show_current(self) -> None:
        issue = self.current
        if issue is None:
            return
        cached = self.cache.detail(issue.key)
        if cached and cached[0] == issue.updated:
            await self._render_card(issue.key, cached[1])
            self._prefetch_next()
            return
        await self._render_card(issue.key, cached[1] if cached else None, note="refreshing…")
        self.fetch_preview(issue)

    @work(exclusive=True, group="preview")
    async def fetch_preview(self, issue: Issue) -> None:
        try:
            data = await self.jira.issue(issue.key)
        except JiraError as err:
            if self.current and self.current.key == issue.key:
                await self._render_message(f"Could not load {issue.key}: {err}")
            return
        self.cache.put_detail(issue.key, data)
        if self.current and self.current.key == issue.key:
            await self._render_card(issue.key, data)
        self._prefetch_next()

    def _prefetch_next(self) -> None:
        """Warm the cache for the row below the cursor, so moving down feels instant."""
        index = self.query_one(IssueList).index
        if index is None or index + 1 >= len(self.shown):
            return
        nxt = self.shown[index + 1]
        cached = self.cache.detail(nxt.key)
        if not (cached and cached[0] == nxt.updated):
            self.prefetch(nxt)

    @work(exclusive=True, group="prefetch")
    async def prefetch(self, issue: Issue) -> None:
        try:
            self.cache.put_detail(issue.key, await self.jira.issue(issue.key))
        except JiraError:
            pass  # best effort; the real fetch reports errors

    # ---------- navigation ----------

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_back(self) -> None:
        search = self.query_one("#search", Input)
        if search.has_focus and search.value:
            search.value = ""
            return
        self.query_one(IssueList).focus()

    async def action_column(self, delta: int) -> None:
        if not self.columns:
            return
        if self.show_all:
            self.notify("All-but-Done view: press a for one column", severity="warning")
            return
        self.col = (self.col + delta) % len(self.columns)
        self.message = ""
        await self._render_list(keep_key=self._current_key())
        if self._viewing_done() and not self._done_loaded:
            self.load_done()

    async def action_toggle_all(self) -> None:
        self.show_all = not self.show_all
        self.col = self.todo_col
        self.message = ""
        await self._render_list(keep_key=self._current_key())

    def action_refresh(self) -> None:
        if self.current:
            self.cache.forget_detail(self.current.key)
        self.message = ""
        self.load_board()

    def action_browser(self) -> None:
        if self.current:
            desktop.open_url(f"{self.config.server}/browse/{self.current.key}")

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def _say(self, message: str) -> None:
        self.message = message
        self._update_status()
        self.notify(message)

    def _replace_issue(self, issue: Issue) -> None:
        self._store([issue if i.key == issue.key else i for i in self.issues])
        self.cache.forget_detail(issue.key)

    # ---------- rank ----------

    async def action_rank(self, where: str) -> None:
        issue = self.current
        if issue is None:
            return
        if self.query_text:
            self.notify("Search active — clear it to reorder", severity="warning")
            return
        if self.sort != "rank":
            self.notify(f"Sorted by {self.sort} — press S and pick Rank to reorder", severity="warning")
            return
        peers = [i for i in self.shown if self._col_of(i) == self._col_of(issue)]
        n = next(k for k, i in enumerate(peers) if i.key == issue.key)
        last = len(peers) - 1
        if where == "up" and n > 0:
            anchor, before = peers[n - 1], True
        elif where == "down" and n < last:
            anchor, before = peers[n + 1], False
        elif where == "top" and n > 0:
            anchor, before = peers[0], True
        elif where == "bottom" and n < last:
            anchor, before = peers[last], False
        elif where == "middle" and n != len(peers) // 2:
            anchor = peers[len(peers) // 2]
            before = n > len(peers) // 2
        else:
            return
        # Move locally first, so the list answers at once; Jira follows in the background.
        rest = [i for i in self.issues if i.key != issue.key]
        at = next(k for k, i in enumerate(rest) if i.key == anchor.key) + (0 if before else 1)
        self._store(rest[:at] + [issue] + rest[at:])
        index = self.query_one(IssueList).index or 0
        if where in ("up", "down", "top"):
            await self._render_list(keep_key=issue.key)
        else:  # cursor stays put, so the next issue is ready to triage
            await self._render_list(fallback_index=index)
        self.rank_issue(issue.key, anchor.key, before)

    @work(group="rank")
    async def rank_issue(self, key: str, anchor: str, before: bool) -> None:
        async with self._rank_lock:  # keep Jira's order of moves the same as the keypresses
            try:
                await self.jira.rank(key, anchor, before)
            except JiraError as err:
                self.notify(str(err), title="Rank failed — reloading", severity="error", timeout=10)
                self.load_board()

    # ---------- status ----------

    def action_status(self) -> None:
        if self.current:
            self.pick_status(self.current)

    @work(group="status")
    async def pick_status(self, issue: Issue) -> None:
        try:
            transitions = await self.jira.transitions(issue.key)
        except JiraError as err:
            self.notify(str(err), title="Could not load transitions", severity="error")
            return
        if not transitions:
            self.notify(f"{issue.key} has no transitions", severity="warning")
            return
        choices = [(tid, name) for tid, _, name in transitions]
        current = next((tid for tid, sid, _ in transitions if sid == issue.status_id), None)
        tid = await self.push_screen_wait(PickScreen(f"{issue.key} → status", choices, current))
        if tid is None:
            return
        _, status_id, name = next(t for t in transitions if t[0] == tid)
        try:
            await self.jira.transition(issue.key, tid)
        except JiraError as err:
            self.notify(str(err), title="Status change failed", severity="error")
            return
        self._replace_issue(replace(issue, status_id=status_id, status_name=name))
        await self._render_list(keep_key=issue.key, fallback_index=self.query_one(IssueList).index or 0)
        self._say(f"{issue.key} → {name}")
        self.load_board()

    # ---------- labels ----------

    def _known_labels(self) -> list[str]:
        labels = {label for i in self.issues for label in i.labels} | set(BUILTIN_LABELS)
        return sorted(labels | self.include | self.exclude, key=str.lower)

    def action_set_label(self) -> None:
        if self.current:
            self.edit_label(self.current)

    @work(group="label")
    async def edit_label(self, issue: Issue) -> None:
        choices = [(label, ("✓ " if label in issue.labels else "  ") + label) for label in self._known_labels()]
        choices.append(("\0new", "+ new label…"))
        label = await self.push_screen_wait(PickScreen(f"{issue.key} labels", choices))
        if label == "\0new":
            label = await self.push_screen_wait(InputScreen("New label", "label name"))
            label = _LABEL_JUNK.sub("", label or "")
        if not label:
            return
        add = label not in issue.labels
        try:
            await self.jira.set_label(issue.key, label, add)
        except JiraError as err:
            self.notify(str(err), title="Label change failed", severity="error")
            return
        labels = issue.labels + (label,) if add else tuple(x for x in issue.labels if x != label)
        self._replace_issue(replace(issue, labels=labels))
        await self._render_list(keep_key=issue.key, fallback_index=self.query_one(IssueList).index or 0)
        self._say(f"{issue.key} {'+' if add else '−'} label {label}")

    def action_label_filter(self) -> None:
        def chosen(result: tuple[set[str], set[str]] | None) -> None:
            if result is not None:
                self.include, self.exclude = result
                self.call_later(self._render_list, self._current_key())

        self.push_screen(MultiPickScreen("Label filter", self._known_labels(), self.include, self.exclude), chosen)

    def action_type_filter(self) -> None:
        types = sorted({i.type for i in self._scope()} | self.types)

        def chosen(result: tuple[set[str], set[str]] | None) -> None:
            if result is not None:
                self.types = result[0]
                self.call_later(self._render_list, self._current_key())

        self.push_screen(MultiPickScreen("Type filter", types, self.types), chosen)

    def action_sort(self) -> None:
        def chosen(sort: str | None) -> None:
            if sort:
                self.sort = sort
                self.call_later(self._render_list, self._current_key())

        self.push_screen(PickScreen("Sort", SORTS, self.sort), chosen)

    # ---------- delete ----------

    def action_delete(self) -> None:
        issue = self.current
        if issue is None:
            return

        def confirmed(yes: bool | None) -> None:
            if yes:
                self.delete_issue(issue)

        self.push_screen(ConfirmScreen(f"Delete {issue.key} “{issue.summary}”? This cannot be undone."), confirmed)

    @work(group="delete")
    async def delete_issue(self, issue: Issue) -> None:
        try:
            await self.jira.delete(issue.key)
        except JiraError as err:
            self.notify(str(err), title="Delete failed", severity="error")
            return
        index = self.query_one(IssueList).index or 0
        self._store([i for i in self.issues if i.key != issue.key])
        self.cache.forget_detail(issue.key)
        await self._render_list(fallback_index=index)
        self._say(f"deleted {issue.key}")

    # ---------- start work ----------

    def action_start_work(self) -> None:
        if self.current:
            self.start_work(self.current)

    @work(group="start")
    async def start_work(self, issue: Issue) -> None:
        agent = await self.push_screen_wait(PickScreen(f"Start {issue.key} with", AGENTS))
        if agent is None:
            return
        self._say(f"starting {issue.key}…")
        try:
            proc = await asyncio.create_subprocess_exec(
                LEGACY_BOARD, "--start-work", issue.key, "--agent", agent,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await proc.communicate()
        except OSError as error:
            self.notify(f"{LEGACY_BOARD}: {error}", title="Start work failed", severity="error")
            return
        lines = (out.decode(errors="replace") + err.decode(errors="replace")).strip().splitlines()
        result = lines[-1] if lines else f"exit status {proc.returncode}"
        if proc.returncode == 0:
            self._say(result)
        else:
            self.message = result
            self._update_status()
            self.notify(result, title="Start work failed", severity="error", timeout=10)
