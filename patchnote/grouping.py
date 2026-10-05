"""Rule-based classification, de-duplication and grouping of changes.
Rules are free, instant and predictable. Anything they can't decide goes to
"other", which is exactly what the AI step will refine later."""
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .github_api import Change

CATEGORY_ORDER = ["breaking", "feature", "fix", "docs", "chore", "other"]
HEADINGS = {
    "breaking": "Breaking changes",
    "feature": "Features",
    "fix": "Fixes",
    "docs": "Documentation",
    "chore": "Maintenance",
    "other": "Other changes",
}

# Conventional commit prefixes: "feat(api)!: ..." -> type, scope, bang, rest
PREFIX_RE = re.compile(r"^(\w+)(\([^)]*\))?(!)?:\s*(.*)$")
PREFIX_MAP = {
    "feat": "feature", "feature": "feature", "perf": "feature",
    "fix": "fix", "bugfix": "fix", "hotfix": "fix",
    "docs": "docs", "doc": "docs",
    "chore": "chore", "refactor": "chore", "style": "chore", "test": "chore",
    "tests": "chore", "ci": "chore", "build": "chore", "deps": "chore",
}
LABEL_MAP = {
    "breaking": "breaking", "breaking-change": "breaking", "breaking change": "breaking",
    "feature": "feature", "enhancement": "feature", "feat": "feature",
    "bug": "fix", "bugfix": "fix", "fix": "fix",
    "documentation": "docs", "docs": "docs",
    "chore": "chore", "dependencies": "chore", "maintenance": "chore", "ci": "chore",
}
# Plain-English messages: only match the START of the title, to avoid false hits
START_KEYWORDS = [
    ("fix", r"^(fix|fixes|fixed|hotfix|resolve|resolves|repair|correct)\b"),
    ("chore", r"^(bump|upgrade|refactor|cleanup|clean up|lint|format|rename|chore|deps)\b"),
    ("feature", r"^(add|adds|added|implement|introduce|support|create|enable|new)\b"),
]
ANYWHERE_KEYWORDS = [
    ("docs", r"\b(readme|documentation|docs?)\b"),
    ("fix", r"\b(bug|crash|regression)\b"),
]


@dataclass
class Classified:
    change: Change
    category: str
    reason: str  # why the rules chose this category (explainable)
    text: str = ""  # the line shown in the release notes


def classify(change: Change) -> tuple[str, str]:
    title = change.title.strip()
    text = f"{title}\n{change.body}"

    # 1. Breaking changes always win
    m = PREFIX_RE.match(title)
    if m and m.group(3):
        return "breaking", "prefix with '!'"
    if "BREAKING CHANGE" in text or re.match(r"^breaking\b", title, re.I):
        return "breaking", "mentions breaking change"
    for label in change.labels:
        if LABEL_MAP.get(label.lower()) == "breaking":
            return "breaking", f"label '{label}'"

    # 2. Labels (a human decided)
    for label in change.labels:
        cat = LABEL_MAP.get(label.lower())
        if cat:
            return cat, f"label '{label}'"

    # 3. Conventional commit prefix
    if m and m.group(1).lower() in PREFIX_MAP:
        return PREFIX_MAP[m.group(1).lower()], f"prefix '{m.group(1).lower()}:'"

    # 4. Plain-English hints
    low = title.lower()
    for cat, pattern in ANYWHERE_KEYWORDS:
        if cat == "docs" and re.search(pattern, low):
            return cat, "mentions documentation"
    for cat, pattern in START_KEYWORDS:
        k = re.match(pattern, low)
        if k:
            return cat, f"starts with '{k.group(1)}'"
    for cat, pattern in ANYWHERE_KEYWORDS:
        k = re.search(pattern, low)
        if k and cat == "fix":
            return cat, f"mentions '{k.group(1)}'"

    return "other", "no rule matched"


def clean_title(title: str) -> str:
    """Drop 'feat(scope):' prefixes and '(#12)' references; capitalise."""
    t = title.strip()
    m = PREFIX_RE.match(t)
    if m and m.group(1).lower() in PREFIX_MAP:
        t = m.group(4)
    t = re.sub(r"\s*\(#\d+\)\s*$", "", t).strip()
    return t[:1].upper() + t[1:]


def _normalise(title: str) -> str:
    """For comparing titles only: 'fix(ui): Crash (#3)' and 'Fix crash' match."""
    t = re.sub(r"\([^)]*\)", "", title.lower())  # drop (#12) and (scope)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def dedupe(changes: list[Change], threshold: float = 0.92) -> tuple[list[Change], int]:
    """Drop repeated/near-identical titles. Returns (unique_changes, dropped_count)."""
    kept: list[Change] = []
    seen: list[str] = []
    for c in changes:
        n = _normalise(c.title)
        if any(n == s or SequenceMatcher(None, n, s).ratio() >= threshold for s in seen):
            continue
        seen.append(n)
        kept.append(c)
    return kept, len(changes) - len(kept)


def group_changes(changes: list[Change]) -> tuple[dict[str, list[Classified]], int]:
    """Return ({category: [Classified, ...]}, duplicates_dropped), in display order."""
    unique, dropped = dedupe(changes)
    groups: dict[str, list[Classified]] = {}
    for c in unique:
        cat, why = classify(c)
        groups.setdefault(cat, []).append(Classified(c, cat, why, clean_title(c.title)))
    return {k: groups[k] for k in CATEGORY_ORDER if k in groups}, dropped


def flatten(groups: dict[str, list[Classified]]) -> list[Classified]:
    return [item for items in groups.values() for item in items]


def regroup(items: list[Classified]) -> dict[str, list[Classified]]:
    """Rebuild the ordered groups after categories may have changed."""
    groups: dict[str, list[Classified]] = {}
    for it in items:
        groups.setdefault(it.category, []).append(it)
    return {k: groups[k] for k in CATEGORY_ORDER if k in groups}