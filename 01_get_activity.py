#!/usr/bin/env python3
"""
Export your GitHub activity (commits, PRs, issues) across organizations.
"""

import argparse
import csv
import datetime as dt
import json
import os
import re
import time
from collections.abc import Iterable
from urllib.parse import urljoin

import requests
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

console = Console()

API_BASE = "https://api.github.com/"
API_VERSION = "2022-11-28"

LINK_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')


def parse_next_link(link_header: str) -> str | None:
    """Extract the 'next' URL from a GitHub Link header."""
    if not link_header:
        return None
    for part in link_header.split(","):
        m = LINK_NEXT_RE.search(part)
        if m:
            return m.group(1)
    return None


class GitHubClient:
    def __init__(self, token: str):
        self.s = requests.Session()
        self.s.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "gh-activity-exporter",
            }
        )

    def _request(self, url_or_path: str, params: dict | None = None) -> requests.Response:
        """Make a GET request with rate-limit handling and retries."""
        url = (
            url_or_path
            if url_or_path.startswith("http")
            else urljoin(API_BASE, url_or_path.lstrip("/"))
        )
        while True:
            try:
                r = self.s.get(url, params=params)
            except requests.RequestException as e:
                console.print(f"[yellow]Network error: {e}. Retrying in 5 seconds...[/yellow]")
                time.sleep(5)
                continue
            # Basic rate-limit handling
            if r.status_code == 403 and r.headers.get("X-RateLimit-Remaining") == "0":
                reset = int(r.headers.get("X-RateLimit-Reset", "0"))
                sleep_for = max(0, reset - int(time.time()) + 5)
                console.print(f"[yellow]Rate limit hit. Waiting {sleep_for} seconds...[/yellow]")
                time.sleep(sleep_for)
                continue
            r.raise_for_status()
            return r

    def paginate(
        self, path: str, params: dict | None = None, items_key: str | None = None
    ) -> Iterable[dict]:
        """
        Pagination via Link header.
        - If items_key is None: response is assumed to be a list.
        - If items_key is set: response is assumed to be an object with that key (e.g. search endpoints use 'items').
        """
        url = path
        first = True
        while url:
            r = self._request(url, params=params if first else None)
            first = False
            data = r.json()
            items = data if items_key is None else data.get(items_key, [])
            yield from items
            url = parse_next_link(r.headers.get("Link", ""))

    def me(self) -> dict:
        return self._request("/user").json()


def iso_date(d: dt.date) -> str:
    return d.strftime("%Y-%m-%d")


def default_rolling_year() -> tuple[dt.date, dt.date]:
    """Return a rolling date range of the last 365 days."""
    today = dt.date.today()
    return (today - dt.timedelta(days=365), today)


def repo_full_name_from_repository_url(repository_url: str) -> str:
    # repository_url looks like: https://api.github.com/repos/OWNER/REPO
    parts = repository_url.rstrip("/").split("/repos/")
    return parts[-1] if len(parts) == 2 else repository_url


def main() -> int:
    """
    Main entry point for the GitHub activity exporter.

    Fetches commits, PRs, and issues for the authenticated user across
    their organization memberships and exports to JSON and CSV files.

    Returns:
        0 on success, 2 if GITHUB_TOKEN is not set.
    """
    ap = argparse.ArgumentParser(
        description="Export your GitHub activity (commits/PRs/issues/etc.) per organization."
    )
    ap.add_argument(
        "--from",
        dest="date_from",
        help="Start date (YYYY-MM-DD). Default: rolling last 365 days.",
    )
    ap.add_argument("--to", dest="date_to", help="End date (YYYY-MM-DD). Default: today.")
    ap.add_argument(
        "--org",
        action="append",
        help="Restrict to specific org(s). Can be used multiple times.",
    )
    ap.add_argument(
        "--out",
        default="github_activity",
        help="Output file prefix (default: github_activity)",
    )
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        console.print("[bold red]ERROR:[/bold red] set GITHUB_TOKEN in your environment.")
        return 2

    if args.date_from and args.date_to:
        d_from = dt.date.fromisoformat(args.date_from)
        d_to = dt.date.fromisoformat(args.date_to)
    else:
        d_from, d_to = default_rolling_year()

    date_range = f"{iso_date(d_from)}..{iso_date(d_to)}"

    gh = GitHubClient(token)
    me = gh.me()
    login = me["login"]

    # Orgs you are a member of
    memberships = list(
        gh.paginate("/user/memberships/orgs", params={"state": "active", "per_page": 100})
    )
    orgs = [m["organization"]["login"] for m in memberships]
    if args.org:
        wanted = set(args.org)
        orgs = [o for o in orgs if o in wanted]

    results: list[dict] = []
    seen = set()  # (kind, url) or (kind, sha)

    def add_record(rec: dict, unique_key: str):
        k = (rec["kind"], unique_key)
        if k in seen:
            return
        seen.add(k)
        results.append(rec)

    console.print(
        Panel(
            f"[bold]User:[/bold] {login}\n"
            f"[bold]Date range:[/bold] {iso_date(d_from)} → {iso_date(d_to)}\n"
            f"[bold]Organizations:[/bold] {', '.join(orgs) if orgs else 'None found'}",
            title="[bold cyan]GitHub Activity Export[/bold cyan]",
            border_style="cyan",
        )
    )

    if not orgs:
        console.print("[yellow]No organizations to process.[/yellow]")
        return 0

    # Calculate total tasks: 7 queries per org (6 issue/PR queries + 1 commit query)
    total_tasks = len(orgs) * 7

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        overall_task = progress.add_task("[cyan]Fetching activity...", total=total_tasks)

        for org in orgs:
            # Issues / PRs search queries
            issue_pr_queries = [
                ("prs_opened", f"org:{org} type:pr author:{login} created:{date_range}"),
                (
                    "prs_merged",
                    f"org:{org} type:pr author:{login} is:merged merged:{date_range}",
                ),
                # Reviews/comments: updated is a practical proxy for reviewed_at/commented_at.
                (
                    "prs_reviewed",
                    f"org:{org} type:pr reviewed-by:{login} updated:{date_range}",
                ),
                (
                    "prs_commented",
                    f"org:{org} type:pr commenter:{login} updated:{date_range}",
                ),
                (
                    "issues_opened",
                    f"org:{org} type:issue author:{login} created:{date_range}",
                ),
                ("involves_me", f"org:{org} involves:{login} updated:{date_range}"),
            ]

            for kind, q in issue_pr_queries:
                progress.update(overall_task, description=f"[cyan]{org}[/cyan] → {kind}")
                for item in gh.paginate(
                    "/search/issues", params={"q": q, "per_page": 100}, items_key="items"
                ):
                    rec = {
                        "kind": kind,
                        "org": org,
                        "repo": repo_full_name_from_repository_url(item.get("repository_url", "")),
                        "number": item.get("number"),
                        "title": item.get("title"),
                        "state": item.get("state"),
                        "url": item.get("html_url"),
                        "created_at": item.get("created_at"),
                        "updated_at": item.get("updated_at"),
                        "closed_at": item.get("closed_at"),
                    }
                    add_record(rec, rec["url"] or f"{org}:{kind}:{rec['repo']}#{rec['number']}")
                progress.advance(overall_task)

            # Commits search query (default branches only)
            progress.update(overall_task, description=f"[cyan]{org}[/cyan] → commits")
            commit_q = f"org:{org} author:{login} committer-date:{date_range}"
            for item in gh.paginate(
                "/search/commits",
                params={"q": commit_q, "per_page": 100},
                items_key="items",
            ):
                sha = item.get("sha")
                commit = item.get("commit", {}) or {}
                author = commit.get("author") or {}
                rec = {
                    "kind": "commits",
                    "org": org,
                    "repo": (item.get("repository") or {}).get("full_name"),
                    "sha": sha,
                    "message": (commit.get("message") or "").splitlines()[0],
                    "url": item.get("html_url"),
                    "author_date": author.get("date"),
                }
                add_record(rec, sha or rec["url"] or json.dumps(rec, sort_keys=True))
            progress.advance(overall_task)

    # Write JSON
    json_path = f"{args.out}_{iso_date(d_from)}_{iso_date(d_to)}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Write CSV
    csv_path = f"{args.out}_{iso_date(d_from)}_{iso_date(d_to)}.csv"
    fieldnames = [
        "kind",
        "org",
        "repo",
        "number",
        "title",
        "state",
        "url",
        "created_at",
        "updated_at",
        "closed_at",
        "sha",
        "message",
        "author_date",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k) for k in fieldnames})

    console.print()
    console.print(f"[bold green]✓[/bold green] Wrote [bold]{len(results)}[/bold] records")
    console.print(f"  [dim]•[/dim] {json_path}")
    console.print(f"  [dim]•[/dim] {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
