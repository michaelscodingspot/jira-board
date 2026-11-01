"""Issue JSON (with Atlassian Document Format description and comments) to Markdown for the preview."""

from __future__ import annotations

from datetime import datetime, timezone

TYPE_EMOJI = {"Bug": "🐞", "Task": "⭐", "Story": "📗", "Epic": "🌟", "Feature": "✨", "Post": "📝"}
LABEL_EMOJI = {"ScanAutoBug": "🤖", "LowPriority": "🔽", "open-source": "🌐", "Blog": "📝", "Validation": "🧪"}


def type_emoji(issue_type: str) -> str:
    if issue_type.startswith("Sub"):
        return "🧩"
    return TYPE_EMOJI.get(issue_type, "▫️")


def label_emoji(label: str) -> str:
    return LABEL_EMOJI.get(label, "🏷️")


def short_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%a, %d %b %y")
    except ValueError:
        return "?"


def long_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return "?"


def card_markdown(data: dict, server: str) -> str:
    key = data.get("key", "")
    f = data.get("fields") or {}
    issue_type = (f.get("issuetype") or {}).get("name") or ""
    labels = f.get("labels") or []
    meta = [
        f"🔑 **{key}**",
        f"{type_emoji(issue_type)} {issue_type}",
        f"**{(f.get('status') or {}).get('name') or '?'}**",
        f"🌱 {short_date(f.get('created') or '')}",
        f"✏️ {short_date(f.get('updated') or '')}",
        "🏷 " + (", ".join(labels) if labels else "None"),
    ]
    people = []
    if f.get("assignee"):
        people.append(f"👤 {f['assignee'].get('displayName', '?')}")
    if f.get("priority"):
        people.append(f"⚑ {f['priority'].get('name', '?')}")
    out = [" · ".join(meta)]
    if people:
        out.append(" · ".join(people))
    out.append(f"## {_escape(f.get('summary') or '')}")
    description = adf_markdown(f.get("description"))
    out.append(description or "_(no description)_")
    comments = (f.get("comment") or {}).get("comments") or []
    if comments:
        out.append("---")
        out.append(f"### 💬 Comments ({len(comments)})")
        for c in comments:
            author = (c.get("author") or {}).get("displayName") or "?"
            out.append(f"**{author}** · _{long_date(c.get('created') or '')}_")
            out.append(adf_markdown(c.get("body")) or "_(empty)_")
    out.append("---")
    out.append(f"_View this issue on Jira: {server}/browse/{key}_")
    return "\n\n".join(out)


# ---------- ADF ----------


def adf_markdown(doc: dict | str | None) -> str:
    if not doc:
        return ""
    if isinstance(doc, str):  # API v2 style plain text
        return doc.strip()
    return _blocks(doc.get("content") or []).strip()


def _blocks(nodes: list[dict], sep: str = "\n\n") -> str:
    return sep.join(part for part in (_block(n) for n in nodes) if part.strip())


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def _block(node: dict) -> str:
    kind = node.get("type")
    attrs = node.get("attrs") or {}
    content = node.get("content") or []
    match kind:
        case "paragraph":
            return _inline(content)
        case "heading":
            return "#" * min(6, int(attrs.get("level") or 1) + 2) + " " + _inline(content)
        case "bulletList":
            return _list(content, None)
        case "orderedList":
            return _list(content, int(attrs.get("order") or 1))
        case "taskList":
            return "\n".join(
                ("☑ " if (i.get("attrs") or {}).get("state") == "DONE" else "☐ ") + _inline(i.get("content") or [])
                for i in content
            )
        case "codeBlock":
            text = "".join(n.get("text", "") for n in content)
            return f"```{attrs.get('language') or ''}\n{text}\n```"
        case "blockquote":
            return _quote(_blocks(content))
        case "panel":
            label = (attrs.get("panelType") or "info").upper()
            return _quote(f"**{label}**\n\n" + _blocks(content))
        case "rule":
            return "---"
        case "mediaSingle" | "mediaGroup":
            return "  \n".join(_block(n) for n in content)
        case "media" | "mediaInline":
            return f"_[attachment: {attrs.get('alt') or attrs.get('id') or 'file'}]_"
        case "table":
            return _table(content)
        case "expand" | "nestedExpand":
            return f"**▸ {attrs.get('title') or ''}**\n\n" + _blocks(content)
        case "text" | "hardBreak" | "mention" | "emoji" | "inlineCard" | "date" | "status":
            return _inline([node])
        case _:
            return _blocks(content)


def _list(items: list[dict], start: int | None) -> str:
    lines: list[str] = []
    number = start or 1
    for item in items:
        marker = f"{number}. " if start is not None else "- "
        body = _blocks(item.get("content") or [], sep="\n").splitlines() or [""]
        lines.append(marker + body[0])
        lines.extend(" " * len(marker) + line if line else "" for line in body[1:])
        number += 1
    return "\n".join(lines)


def _table(rows: list[dict]) -> str:
    cells = [
        [_blocks(cell.get("content") or [], sep=" ").replace("\n", " ").replace("|", "\\|") for cell in row.get("content") or []]
        for row in rows
    ]
    cells = [r for r in cells if r]
    if not cells:
        return ""
    width = max(len(r) for r in cells)
    cells = [r + [""] * (width - len(r)) for r in cells]
    out = ["| " + " | ".join(cells[0]) + " |", "|" + "---|" * width]
    out += ["| " + " | ".join(r) + " |" for r in cells[1:]]
    return "\n".join(out)


def _escape(text: str) -> str:
    for ch in "\\`*_[]<>":
        text = text.replace(ch, "\\" + ch)
    return text


def _inline(nodes: list[dict]) -> str:
    out: list[str] = []
    for node in nodes:
        kind = node.get("type")
        attrs = node.get("attrs") or {}
        if kind == "text":
            out.append(_marked(node.get("text", ""), node.get("marks") or []))
        elif kind == "hardBreak":
            out.append("  \n")
        elif kind == "mention":
            text = attrs.get("text") or "user"
            out.append(f"**{text if text.startswith('@') else '@' + text}**")
        elif kind == "emoji":
            out.append(attrs.get("text") or attrs.get("shortName") or "")
        elif kind in ("inlineCard", "blockCard", "embedCard"):
            url = attrs.get("url") or ""
            out.append(f"[{url}]({url})" if url else "")
        elif kind == "date":
            try:
                ts = int(attrs.get("timestamp")) / 1000
                out.append(datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d"))
            except (TypeError, ValueError):
                pass
        elif kind == "status":
            out.append(f"`[{attrs.get('text', '')}]`")
        elif kind in ("media", "mediaInline"):
            out.append(_block(node))
        else:
            out.append(_inline(node.get("content") or []))
    return "".join(out)


def _marked(text: str, marks: list[dict]) -> str:
    kinds = {m.get("type"): m.get("attrs") or {} for m in marks}
    if "code" in kinds:
        text = f"`{text}`"
    else:
        lead = text[: len(text) - len(text.lstrip())]
        trail = text[len(text.rstrip()):]
        core = _escape(text.strip())
        if core:
            if "strike" in kinds:
                core = f"~~{core}~~"
            if "em" in kinds:
                core = f"*{core}*"
            if "strong" in kinds:
                core = f"**{core}**"
        text = lead + core + trail
    if "link" in kinds and kinds["link"].get("href"):
        text = f"[{text}]({kinds['link']['href']})"
    return text
