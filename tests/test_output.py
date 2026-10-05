import json

import httpx
import pytest

from patchnote.github_api import Change, GitHub
from patchnote.grouping import group_changes
from patchnote.output import post_webhook, publish_release, render_body, render_entry, update_changelog


def groups():
    g, _ = group_changes([
        Change(kind="pr", title="feat: Add search", number=7, url="https://x/pr/7", sha="a" * 40),
        Change(kind="commit", title="Fix crash", url="https://x/c/1", sha="b" * 40),
    ])
    return g


def test_render_technical_has_refs_customer_does_not():
    tech = render_body(groups(), "o/r", "v1", "v2", "technical")
    cust = render_body(groups(), "o/r", "v1", "v2", "customer")
    assert "### Features" in tech and "([#7](https://x/pr/7))" in tech and "([bbbbbbb](https://x/c/1))" in tech
    assert "#7" not in cust and "bbbbbbb" not in cust
    assert tech.endswith("https://github.com/o/r/compare/v1...v2")


def test_changelog_is_idempotent_and_newest_first(tmp_path):
    f = tmp_path / "CHANGELOG.md"
    update_changelog(f, render_entry("v0.1.0", "2026-01-01", "old notes"), "v0.1.0")
    update_changelog(f, render_entry("v0.2.0", "2026-02-01", "new notes"), "v0.2.0")
    update_changelog(f, render_entry("v0.2.0", "2026-02-01", "REGENERATED"), "v0.2.0")
    text = f.read_text(encoding="utf-8")
    assert text.count("## v0.2.0") == 1 and "REGENERATED" in text and "new notes" not in text
    assert text.index("## v0.2.0") < text.index("## v0.1.0") and text.startswith("# Changelog")


def _gh(handler):
    return GitHub(client=httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(handler)))


def test_publish_creates_when_missing_updates_when_present():
    calls = []
    def handler(req):
        calls.append((req.method, req.url.path))
        if req.method == "GET":
            return httpx.Response(404 if "missing" in req.url.path else 200, json={"id": 5})
        return httpx.Response(200, json={"html_url": "https://github.com/o/r/releases/tag/x"})
    gh = _gh(handler)
    assert publish_release(gh, "o/r", "missing", "notes").endswith("/x")
    assert calls[-1] == ("POST", "/repos/o/r/releases")
    publish_release(gh, "o/r", "present", "notes")
    assert calls[-1] == ("PATCH", "/repos/o/r/releases/5")


def test_publish_reports_permission_problem():
    gh = _gh(lambda req: httpx.Response(404) if req.method == "GET" else httpx.Response(403, json={}))
    with pytest.raises(RuntimeError, match="permission"):
        publish_release(gh, "o/r", "v1", "notes")


def test_webhook_only_allows_known_hosts():
    for bad in ("http://discord.com/api/webhooks/1/x", "https://evil.example/hook", "https://169.254.169.254/"):
        with pytest.raises(RuntimeError):
            post_webhook(bad, "o/r", "v1", "notes")


def test_webhook_payload_shapes_and_truncation():
    sent = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: (sent.append(json.loads(r.content)), httpx.Response(204))[1]))
    post_webhook("https://discord.com/api/webhooks/1/x", "o/r", "v1", "n" * 5000, client)
    post_webhook("https://hooks.slack.com/services/T/B/x", "o/r", "v1", "hi", client)
    assert "content" in sent[0] and len(sent[0]["content"]) <= 1910
    assert "text" in sent[1]