from patchnote.github_api import Change
from patchnote.grouping import classify, clean_title, dedupe, group_changes


def ch(title, labels=None, body=""):
    return Change(kind="commit", title=title, body=body, labels=labels or [])


def test_conventional_prefixes():
    assert classify(ch("feat(api): add search"))[0] == "feature"
    assert classify(ch("fix: crash on empty input"))[0] == "fix"
    assert classify(ch("docs: update guide"))[0] == "docs"
    assert classify(ch("chore: bump deps"))[0] == "chore"


def test_breaking_wins_over_everything():
    assert classify(ch("feat!: drop python 3.8"))[0] == "breaking"
    assert classify(ch("Remove old API", body="BREAKING CHANGE: endpoint gone"))[0] == "breaking"
    assert classify(ch("Add search", labels=["breaking"]))[0] == "breaking"


def test_labels_beat_wording():
    assert classify(ch("Tweak login", labels=["bug"]))[0] == "fix"


def test_plain_english_hints():
    assert classify(ch("Fix typo in header"))[0] == "fix"
    assert classify(ch("Add portfolio README"))[0] == "docs"   # README mention wins
    assert classify(ch("Add dark mode"))[0] == "feature"


def test_unclear_goes_to_other_not_guessed():
    # 'requirements' mid-sentence must NOT trigger a rule
    assert classify(ch("Hosted Whisper via Groq, health endpoint, split requirements"))[0] == "other"
    assert classify(ch("Lean production requirements"))[0] == "other"


def test_clean_title():
    assert clean_title("feat(ui): add dark mode (#12)") == "Add dark mode"
    assert clean_title("fix login") == "Fix login"


def test_dedupe_merges_repeats_and_near_repeats():
    items = [ch("Add portfolio README"), ch("Add portfolio README"),
             ch("Fix crash (#3)"), ch("fix: crash"), ch("Something else")]
    unique, dropped = dedupe(items)
    assert dropped == 2 and len(unique) == 3


def test_group_order_and_empty_groups_omitted():
    groups, dropped = group_changes([ch("Fix a"), ch("Add b"), ch("feat!: c"), ch("zzz")])
    assert list(groups) == ["breaking", "feature", "fix", "other"]