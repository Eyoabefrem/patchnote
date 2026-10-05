"""Turn grouped changes into Markdown, a CHANGELOG.md entry, a GitHub Release and a chat message."""
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .github_api import GitHub
from .grouping import HEADINGS, Classified

DISCORD_HOSTS = {"discord.com", "discordapp.com"}
SLACK_HOSTS = {"hooks.slack.com"}


def _ref(it: Classified) -> str:
    c = it.change
    if c.number:
        return f" ([#{c.number}]({c.url}))"
    return f" ([{c.sha[:7]}]({c.url}))" if c.sha and c.url else ""


def render_body(groups: dict[str, list[Classified]], repo: str, base: str, tag: str,
                tone: str = "technical", explain: bool = False) -> str:
    lines: list[str] = []
    for cat, items in groups.items():
        lines.append(f"### {HEADINGS[cat]}")
        for it in items:
            ref = _ref(it) if tone == "technical" else ""
            why = f"  <!-- {it.reason} -->" if explain else ""
            lines.append(f"- {it.text}{ref}{why}")
        lines.append("")
    if not groups:
        lines += ["No notable changes in this release.", ""]
    lines.append(f"**Full changelog**: https://github.com/{repo}/compare/{base}...{tag}")
    return "\n".join(lines)


def render_entry(tag: str, date: str, body: str) -> str:
    return f"## {tag} ({date})\n\n{body}\n"


def update_changelog(path: Path, entry: str, tag: str) -> str:
    """Insert the entry under the title; re-running for the same tag replaces it (idempotent)."""
    text = path.read_text(encoding="utf-8") if path.exists() else "# Changelog\n\n"
    section = re.compile(rf"^## {re.escape(tag)} \(.*?(?=^## |\Z)", re.S | re.M)
    if section.search(text):
        text = section.sub(lambda _: entry + "\n", text, count=1)
    else:
        m = re.match(r"(# [^\n]*\n+)", text)
        head, rest = (m.group(1), text[m.end():]) if m else ("# Changelog\n\n", text)
        text = head + entry + "\n" + rest
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return text


def publish_release(gh: GitHub, repo: str, tag: str, body: str) -> str:
    """Create the GitHub Release for `tag`, or update it if it already exists."""
    r = gh.http.get(f"/repos/{repo}/releases/tags/{tag}")
    if r.status_code == 200:
        r = gh.http.patch(f"/repos/{repo}/releases/{r.json()['id']}", json={"body": body})
    elif r.status_code == 404:
        r = gh.http.post(f"/repos/{repo}/releases", json={"tag_name": tag, "name": tag, "body": body})
    if r.status_code in (401, 403):
        raise RuntimeError("GitHub refused the release. Check that GITHUB_TOKEN has permission to write contents.")
    r.raise_for_status()
    return r.json()["html_url"]


def post_webhook(url: str, repo: str, tag: str, body: str, client: httpx.Client | None = None) -> None:
    """Send the notes to Discord or Slack. Only known webhook hosts are allowed."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in DISCORD_HOSTS | SLACK_HOSTS:
        raise RuntimeError("WEBHOOK_URL must be an https Discord or Slack webhook.")
    text = f"**{repo} {tag}**\n\n{body}"
    if len(text) > 1900:
        text = text[:1900].rstrip() + "\n..."
    payload = {"content": text} if parsed.hostname in DISCORD_HOSTS else {"text": text}
    (client or httpx).post(url, json=payload, timeout=30).raise_for_status()