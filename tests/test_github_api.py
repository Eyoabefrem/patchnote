import httpx

from patchnote.github_api import (GitHub, collect_changes, extract_pr_number,
                                  newest_tag, parse_semver, previous_tag)

TAGS = ["v1.0.0", "v1.1.0", "v1.10.0", "v1.2.0", "nightly", "v2.0.0-rc1"]


def test_parse_semver():
    assert parse_semver("v1.2.3") == (1, 2, 3)
    assert parse_semver("1.2.3") == (1, 2, 3)
    assert parse_semver("v2.0.0-rc1") is None
    assert parse_semver("nightly") is None


def test_newest_tag_uses_numeric_not_text_order():
    assert newest_tag(TAGS) == "v1.10.0"  # text order would wrongly pick v1.2.0


def test_previous_tag():
    assert previous_tag(TAGS, "v1.10.0") == "v1.2.0"
    assert previous_tag(TAGS, "v1.0.0") is None
    assert previous_tag(TAGS, "nightly") is None


def test_extract_pr_number():
    assert extract_pr_number("Fix login bug (#42)") == 42
    assert extract_pr_number("Merge pull request #7 from a/b") == 7
    assert extract_pr_number("Plain commit message") is None


def _fake_github() -> GitHub:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/tags"):
            return httpx.Response(200, json=[{"name": "v1.1.0"}, {"name": "v1.0.0"}])
        if "/compare/" in path:
            commit = lambda sha, msg: {"sha": sha, "html_url": f"https://x/{sha}",
                                       "author": {"login": "eyoab"},
                                       "commit": {"message": msg, "author": {"name": "Eyoab"}}}
            return httpx.Response(200, json={"commits": [
                commit("aaa1111", "Add voice replies (#5)"),
                commit("bbb2222", "Fix crash on empty message\n\nDetails here"),
                commit("ccc3333", "Merge branch 'main' into dev"),
            ]})
        if path.endswith("/pulls/5"):
            return httpx.Response(200, json={"title": "Add voice replies", "body": "Adds TTS",
                                             "html_url": "https://x/pr/5", "user": {"login": "eyoab"},
                                             "labels": [{"name": "feature"}]})
        return httpx.Response(404, json={})
    return GitHub(client=httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(handler)))


def test_collect_changes_with_mocked_github():
    base, tag, changes = collect_changes("o/r", gh=_fake_github())
    assert (base, tag) == ("v1.0.0", "v1.1.0")
    assert [c.kind for c in changes] == ["pr", "commit"]  # merge commit skipped
    assert changes[0].labels == ["feature"] and changes[0].number == 5
    assert changes[1].title == "Fix crash on empty message" and changes[1].body == "Details here"