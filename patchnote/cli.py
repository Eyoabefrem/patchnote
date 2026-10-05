import argparse
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from .github_api import GitHub, collect_changes
from .grouping import flatten, group_changes, regroup
from .llm import TONES, rewrite
from .output import post_webhook, publish_release, render_body, render_entry, update_changelog


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def main() -> None:
    load_dotenv()
    p = argparse.ArgumentParser(description="Generate release notes between two tags.")
    p.add_argument("--repo", required=True, help="owner/name, e.g. Eyoabefrem/crop-advisor")
    p.add_argument("--tag", help="release tag to describe (default: newest version tag)")
    p.add_argument("--base", help="compare against this ref (default: previous version tag)")
    p.add_argument("--tone", choices=list(TONES), default="technical")
    p.add_argument("--no-ai", action="store_true", help="rules only, no AI call")
    p.add_argument("--explain", action="store_true", help="add the reason for each category as a hidden comment")
    p.add_argument("--changelog", metavar="PATH", help="write/update this CHANGELOG.md")
    p.add_argument("--publish", action="store_true", help="create/update the GitHub Release (needs GITHUB_TOKEN)")
    p.add_argument("--notify", action="store_true", help="post to the Discord/Slack webhook in WEBHOOK_URL")
    args = p.parse_args()

    gh = GitHub()
    try:
        base, tag, changes = collect_changes(args.repo, args.tag, args.base, gh=gh)
        groups, dropped = group_changes(changes)
        items, note = flatten(groups), "rules only"
        if not args.no_ai and items:
            items, status = rewrite(items, args.tone)
            groups = regroup(items)
            note = f"AI rewrite ({args.tone})" if status["ai_used"] else "AI unavailable, rules only"

        body = render_body(groups, args.repo, base, tag, args.tone, args.explain)
        log(f"{args.repo}: {base} -> {tag} | {len(changes)} changes, {dropped} duplicates merged | {note}\n")
        print(body)

        if args.changelog:
            update_changelog(Path(args.changelog), render_entry(tag, date.today().isoformat(), body), tag)
            log(f"\nUpdated {args.changelog}")
        if args.publish:
            log(f"\nPublished release: {publish_release(gh, args.repo, tag, body)}")
        if args.notify:
            url = os.getenv("WEBHOOK_URL")
            if not url:
                raise RuntimeError("Set WEBHOOK_URL to use --notify.")
            post_webhook(url, args.repo, tag, body)
            log("\nNotification sent.")
    except RuntimeError as e:
        raise SystemExit(f"Error: {e}")


if __name__ == "__main__":
    main()