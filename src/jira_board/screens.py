"""Modal dialogs, styled like notion-tui's: confirm, single pick, multi pick, text input, help."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Markdown, OptionList
from textual.widgets.option_list import Option

DIALOG_CSS = """
#dialog { width: 72; height: auto; max-height: 80%; padding: 1 2; border: round $accent; background: $surface; }
#dialog Label { width: 100%; }
#dialog OptionList { height: auto; max-height: 24; margin: 1 0; border: none; background: transparent; }
#dialog Input { margin: 1 0; }
#dialog .hint { color: $text-muted; }
"""


class ConfirmScreen(ModalScreen[bool]):
    AUTO_FOCUS = "#no"
    BINDINGS = [
        Binding("y", "answer(True)", "yes"),
        Binding("n,escape", "answer(False)", "no"),
    ]
    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    #confirm { width: 60; height: auto; padding: 1 2; border: round $error; background: $surface; }
    #confirm Label { width: 100%; margin-bottom: 1; }
    #buttons { height: auto; align-horizontal: right; }
    #buttons Button { margin-left: 2; }
    """

    def __init__(self, question: str, yes: str = "Delete") -> None:
        super().__init__()
        self.question = question
        self.yes = yes

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm"):
            yield Label(self.question, markup=False)
            with Horizontal(id="buttons"):
                yield Button(f"{self.yes} (y)", variant="error", id="yes")
                yield Button("Cancel (n)", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_answer(self, yes: bool) -> None:
        self.dismiss(yes)


class PickScreen(ModalScreen[str | None]):
    """Pick one of `choices` ((id, label) pairs). Returns the id, or None on escape."""

    AUTO_FOCUS = "OptionList"
    BINDINGS = [Binding("escape,q", "close", "close")]
    DEFAULT_CSS = "PickScreen { align: center middle; }" + DIALOG_CSS

    def __init__(self, title: str, choices: list[tuple[str, str]], current: str | None = None) -> None:
        super().__init__()
        self.title_text = title
        self.choices = choices
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield OptionList(*(Option(Text(label), id=cid) for cid, label in self.choices))
            yield Label("↑/↓ move · enter choose · esc cancel", classes="hint")

    def on_mount(self) -> None:
        self.query_one("#dialog").border_title = self.title_text
        ids = [cid for cid, _ in self.choices]
        if self.current in ids:
            self.query_one(OptionList).highlighted = ids.index(self.current)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_close(self) -> None:
        self.dismiss(None)


class MultiPickScreen(ModalScreen[tuple[set[str], set[str]] | None]):
    """Mark items as included (✓) and, when `allow_exclude`, excluded (✗).

    space/i toggles include, x toggles exclude, a clears all, enter applies, esc cancels.
    Returns (included, excluded), or None on escape.
    """

    AUTO_FOCUS = "OptionList"
    BINDINGS = [
        Binding("space,i", "toggle(False)", "include", priority=True),
        Binding("x", "toggle(True)", "exclude"),
        Binding("a", "clear", "all"),
        Binding("escape,q", "close", "cancel"),
    ]
    DEFAULT_CSS = "MultiPickScreen { align: center middle; }" + DIALOG_CSS

    def __init__(self, title: str, items: list[str], include: set[str], exclude: set[str] | None = None) -> None:
        super().__init__()
        self.title_text = title
        self.items = items
        self.include = set(include)
        self.allow_exclude = exclude is not None
        self.exclude = set(exclude or ())

    def _prompt(self, item: str) -> Text:
        if item in self.include:
            return Text.assemble(("✓ ", "bold green"), item)
        if item in self.exclude:
            return Text.assemble(("✗ ", "bold red"), (item, "strike"))
        return Text("  " + item)

    def compose(self) -> ComposeResult:
        hint = "space include · x exclude · a all · enter apply · esc cancel" if self.allow_exclude \
            else "space toggle · a all · enter apply · esc cancel"
        with Vertical(id="dialog"):
            yield OptionList(*(Option(self._prompt(i), id=i) for i in self.items))
            yield Label(hint, classes="hint")

    def on_mount(self) -> None:
        self.query_one("#dialog").border_title = self.title_text

    def action_toggle(self, exclude: bool) -> None:
        if exclude and not self.allow_exclude:
            return
        options = self.query_one(OptionList)
        index = options.highlighted
        if index is None:
            return
        item = self.items[index]
        target, other = (self.exclude, self.include) if exclude else (self.include, self.exclude)
        other.discard(item)
        if item in target:
            target.discard(item)
        else:
            target.add(item)
        options.replace_option_prompt_at_index(index, self._prompt(item))

    def action_clear(self) -> None:
        self.include.clear()
        self.exclude.clear()
        options = self.query_one(OptionList)
        for index, item in enumerate(self.items):
            options.replace_option_prompt_at_index(index, self._prompt(item))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss((self.include, self.exclude))

    def action_close(self) -> None:
        self.dismiss(None)


class InputScreen(ModalScreen[str | None]):
    AUTO_FOCUS = "Input"
    BINDINGS = [Binding("escape", "close", "cancel")]
    DEFAULT_CSS = "InputScreen { align: center middle; }" + DIALOG_CSS

    def __init__(self, title: str, placeholder: str = "") -> None:
        super().__init__()
        self.title_text = title
        self.placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Input(placeholder=self.placeholder)
            yield Label("enter save · esc cancel", classes="hint")

    def on_mount(self) -> None:
        self.query_one("#dialog").border_title = self.title_text

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_close(self) -> None:
        self.dismiss(None)


HELP = """\
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
| `f` | label filter (include / exclude) |
| `y` | type filter |
| `S` | sort |
| `d` | delete issue |
| `o` `enter` | open in browser |
| `w` | start work: pick agent, claim clone, open terminal |
| `r` | refresh from Jira |
| `?` | this help |
| `q` | quit |

Ranking is refused while a search is typed or the sort is not Rank.
"""


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,q,question_mark", "close", "close")]
    DEFAULT_CSS = """
    HelpScreen { align: center middle; }
    #help { width: 76; height: 80%; padding: 0 1; border: round $accent; background: $surface; }
    #help Markdown { background: transparent; }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help"):
            yield Markdown(HELP)

    def on_mount(self) -> None:
        self.query_one("#help").border_title = "Keys"

    def action_close(self) -> None:
        self.dismiss(None)
