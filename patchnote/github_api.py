"""Fetch what changed between two release tags using the GitHub REST API."""
import os
import re
from dataclasses import dataclass, field

import httpx

API = "https://api.github.com"
SEMVER_TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")  # v1.2.3 or 1.2.3 (pre-releases ignored)
PR_REF = re.compile(r"\(#(\d+)\)|Merge pull request #(\d+)")
MAX_BODY = 1000  # PR/commit text is untrusted input; keep it short


@dataclass
class Change:
    kind: str  # "pr" or "commit"
    title: str
    body: str = ""
    number: int | None = None
    author: str = ""
    url: str = ""
    labels: list[str] = field(default_factory=list)
    sha: str = ""


# ---------- pure helpers (easy to test, no network) ----------

def parse_semver(tag: str) -> tuple[int, int, int] | None:
    m = SEMVER_TAG.match(tag)
    return tuple(int(x) for x in m.groups()) if m else None


def newest_tag(tags: list[str]) -> str | None:
    versions = [(parse_semver(t), t) for t in tags if parse_semver(t)]
    return max(versions)[1] if versions else None


def previous_tag(tags: list[str], target: str) -> str | None:
    target_v = parse_semver(target)
    if target_v is None:
        return None
    older = [(parse_semver(t), t) for t in tags if parse_semver(t) and parse_semver(t) < target_v]
    return max(older)[1] if older else None


def extract_pr_number(message: str) -> int | None:
    m = PR_REF.search(message)
    return int(m.group(1) or m.group(2)) if m else None


def _clip(text: str | None) -> str:
    return (text or "").strip()[:MAX_BODY]


# ---------- GitHub client ----------

class GitHub:
    def __init__(self, token: str | None = None, client: httpx.Client | None = None):
        token = token or os.getenv("GITHUB_TOKEN")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.http = client or httpx.Client(base_url=API, headers=headers, timeout=30)

    def _get(self, path: str, **params):
        r = self.http.get(path, params=params)
        if r.status_code == 404:
            raise RuntimeError(f"Not found: {path}. Check the repo name, the tag, and that the repo is public (or set GITHUB_TOKEN).")
        if r.status_code in (403, 429):
            raise RuntimeError("GitHub rate limit reached. Set GITHUB_TOKEN to raise the limit.")
        r.raise_for_status()
        return r.json()

    def list_tags(self, repo: str) -> list[str]:
        tags, page = [], 1
        while page <= 5:
            batch = self._get(f"/repos/{repo}/tags", per_page=100, page=page)
            tags += [t["name"] for t in batch]
            if len(batch) < 100:
                break
            page += 1
        return tags

    def compare(self, repo: str, base: str, head: str) -> list[dict]:
        commits, page = [], 1
        while page <= 10:
            data = self._get(f"/repos/{repo}/compare/{base}...{head}", per_page=100, page=page)
            batch = data.get("commits", [])
            commits += batch
            if len(batch) < 100:
                break
            page += 1
        return commits

    def get_pr(self, repo: str, number: int) -> dict | None:
        try:
            return self._get(f"/repos/{repo}/pulls/{number}")
        except RuntimeError:
            return None  # not a PR in this repo: fall back to the commit


def collect_changes(repo: str, tag: str | None = None, base: str | None = None,
                    gh: GitHub | None = None) -> tuple[str, str, list[Change]]:
    """Return (base_tag, head_tag, changes) for the release ending at `tag`."""
    gh = gh or GitHub()
    tags = gh.list_tags(repo)
    tag = tag or newest_tag(tags)
    if not tag:
        raise RuntimeError("No version tags found (expected tags like v1.2.3).")
    base = base or previous_tag(tags, tag)
    if not base:
        raise RuntimeError(f"No earlier tag found before {tag}. Pass --base to compare against a specific ref.")

    changes: list[Change] = []
    seen_prs: set[int] = set()
    for c in gh.compare(repo, base, tag):
        message = c["commit"]["message"]
        first_line = message.splitlines()[0] if message else ""
        pr_no = extract_pr_number(message)

        if pr_no and pr_no in seen_prs:
            continue
        pr = gh.get_pr(repo, pr_no) if pr_no else None
        if pr:
            seen_prs.add(pr_no)
            changes.append(Change(
                kind="pr", title=pr["title"], body=_clip(pr.get("body")), number=pr_no,
                author=(pr.get("user") or {}).get("login", ""), url=pr["html_url"],
                labels=[l["name"] for l in pr.get("labels", [])], sha=c["sha"],
            ))
        elif not first_line.startswith("Merge branch"):
            changes.append(Change(
                kind="commit", title=first_line, body=_clip("\n".join(message.splitlines()[1:])),
                author=((c.get("author") or {}).get("login")) or c["commit"]["author"]["name"],
                url=c["html_url"], sha=c["sha"],
            ))
    return base, tag, changes