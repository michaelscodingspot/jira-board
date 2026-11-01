"""Async Jira Cloud REST client: the same endpoints the fzf jira-board used."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import Config

LIST_FIELDS = "key,summary,issuetype,status,labels,comment,created,updated"
DETAIL_FIELDS = "summary,issuetype,status,created,updated,assignee,reporter,priority,labels,description,comment"
PAGE_SIZE = 100
MAX_ISSUES = 2000  # per query, same ceiling as the old board


class JiraError(Exception):
    pass


@dataclass(frozen=True)
class Column:
    name: str
    status_ids: tuple[str, ...]


@dataclass(frozen=True)
class Issue:
    key: str
    summary: str
    type: str
    status_id: str
    status_name: str
    labels: tuple[str, ...]
    comments: int
    created: str
    updated: str

    @property
    def number(self) -> int:
        try:
            return int(self.key.rsplit("-", 1)[1])
        except (IndexError, ValueError):
            return 0


def issue_from_json(data: dict) -> Issue:
    fields = data.get("fields") or {}
    status = fields.get("status") or {}
    return Issue(
        key=data["key"],
        summary=fields.get("summary") or "",
        type=(fields.get("issuetype") or {}).get("name") or "",
        status_id=str(status.get("id") or ""),
        status_name=status.get("name") or "",
        labels=tuple(fields.get("labels") or ()),
        comments=int((fields.get("comment") or {}).get("total") or 0),
        created=fields.get("created") or "",
        updated=fields.get("updated") or "",
    )


class Jira:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.http = httpx.AsyncClient(
            base_url=config.server,
            auth=(config.login, config.token),
            headers={"Accept": "application/json"},
            timeout=30.0,
        )

    async def _request(self, method: str, path: str, expect: tuple[int, ...] = (200,), **kwargs) -> httpx.Response:
        try:
            response = await self.http.request(method, path, **kwargs)
        except httpx.HTTPError as err:
            raise JiraError(f"{method} {path}: {err}") from err
        if response.status_code not in expect:
            raise JiraError(f"{method} {path}: HTTP {response.status_code} {_error_text(response)}")
        return response

    async def board(self) -> tuple[str, list[Column]]:
        """Board name and its columns (columns without statuses are skipped)."""
        data = (await self._request("GET", f"/rest/agile/1.0/board/{self.config.board_id}/configuration")).json()
        columns = [
            Column(c["name"], tuple(str(s["id"]) for s in c.get("statuses", [])))
            for c in data.get("columnConfig", {}).get("columns", [])
            if c.get("statuses")
        ]
        return data.get("name") or self.config.board_name, columns

    async def board_issues(self, jql: str) -> list[Issue]:
        """All issues on the board matching `jql`, following pages up to MAX_ISSUES."""
        issues: list[Issue] = []
        while len(issues) < MAX_ISSUES:
            params = {"jql": jql, "fields": LIST_FIELDS, "startAt": len(issues), "maxResults": PAGE_SIZE}
            data = (await self._request("GET", f"/rest/agile/1.0/board/{self.config.board_id}/issue", params=params)).json()
            page = data.get("issues") or []
            issues.extend(issue_from_json(i) for i in page)
            if not page or len(issues) >= int(data.get("total") or 0):
                break
        return issues

    async def issue(self, key: str) -> dict:
        return (await self._request("GET", f"/rest/api/3/issue/{key}", params={"fields": DETAIL_FIELDS})).json()

    async def rank(self, key: str, anchor: str, before: bool) -> None:
        body = {"issues": [key], ("rankBeforeIssue" if before else "rankAfterIssue"): anchor}
        await self._request("PUT", "/rest/agile/1.0/issue/rank", expect=(204,), json=body)

    async def transitions(self, key: str) -> list[tuple[str, str, str]]:
        """(transition id, target status id, target status name) the issue can move to now."""
        data = (await self._request("GET", f"/rest/api/3/issue/{key}/transitions")).json()
        return [(t["id"], str(t["to"]["id"]), t["to"]["name"]) for t in data.get("transitions", [])]

    async def transition(self, key: str, transition_id: str) -> None:
        await self._request("POST", f"/rest/api/3/issue/{key}/transitions", expect=(204,), json={"transition": {"id": transition_id}})

    async def set_label(self, key: str, label: str, add: bool) -> None:
        body = {"update": {"labels": [{("add" if add else "remove"): label}]}}
        await self._request("PUT", f"/rest/api/3/issue/{key}", expect=(204,), json=body)

    async def delete(self, key: str) -> None:
        await self._request("DELETE", f"/rest/api/3/issue/{key}", expect=(204,))


def _error_text(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:200]
    messages = list(data.get("errorMessages") or []) + [f"{k}: {v}" for k, v in (data.get("errors") or {}).items()]
    return "; ".join(messages) or response.text[:200]
