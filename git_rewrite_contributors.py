#!/usr/bin/env python3
"""
git_remove_contributor.py
─────────────────────────
Fully interactive TUI to:
  • Erase a contributor from Git history (commits, co-author trailers, and all)
  • Normalize contributor identities
  • Fill missing GitHub contribution days with backdated commits

No hardcoded values — everything is collected at runtime.

Deps (auto-installed on first run):
  pip install rich questionary git-filter-repo requests
"""

import subprocess
import sys
import re
import argparse
import datetime
import os
import random
from collections import defaultdict, namedtuple
from pathlib import Path


# ── auto-install deps ─────────────────────────────────────────────────────────

def ensure_deps():
    needed = {"rich": "rich", "questionary": "questionary", "requests": "requests"}
    for mod, pkg in needed.items():
        try:
            __import__(mod)
        except ImportError:
            print(f"[setup] Installing {pkg}…")
            subprocess.run([sys.executable, "-m", "pip", "install", pkg, "-q"], check=True)

ensure_deps()

import questionary
import requests
from questionary import Style as QStyle
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

Q_STYLE = QStyle([
    ("qmark",        "fg:#e5c07b bold"),
    ("question",     "fg:#abb2bf bold"),
    ("answer",       "fg:#98c379 bold"),
    ("pointer",      "fg:#61afef bold"),
    ("highlighted",  "fg:#61afef bold"),
    ("selected",     "fg:#98c379"),
    ("separator",    "fg:#5c6370"),
    ("instruction",  "fg:#5c6370 italic"),
    ("text",         "fg:#abb2bf"),
    ("disabled",     "fg:#5c6370 italic"),
])

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

# Identity of the person running the script — collected interactively at startup.
UserIdentity = namedtuple("UserIdentity", ["name", "username", "email"])


# ── git helpers ───────────────────────────────────────────────────────────────

def run(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        console.print(f"\n[bold red]✗ Command failed:[/] {' '.join(cmd)}")
        console.print(f"[dim]{r.stderr.strip()}[/]")
        sys.exit(1)
    return r.stdout


def is_git_repo(path):
    r = subprocess.run(["git", "rev-parse", "--git-dir"],
                       cwd=path, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return r.returncode == 0


def get_filter_repo_cmd(path):
    candidates = [
        ["git", "filter-repo"],
        ["git-filter-repo"],
    ]

    scripts_hint = None
    if sys.platform.startswith("win"):
        version_tag = f"Python{sys.version_info.major}{sys.version_info.minor}"
        user_scripts = Path.home() / "AppData" / "Roaming" / "Python" / version_tag / "Scripts"
        exe_scripts = Path(sys.executable).resolve().parent / "Scripts"
        scripts_hint = user_scripts

        for exe_path in [user_scripts / "git-filter-repo.exe", exe_scripts / "git-filter-repo.exe"]:
            if exe_path.exists():
                candidates.append([str(exe_path)])

    for base_cmd in candidates:
        try:
            r = subprocess.run(base_cmd + ["--version"],
                               cwd=path, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            continue
        if r.returncode == 0:
            return base_cmd

    console.print("[bold red]✗[/] [bold]git-filter-repo[/] not found.")
    console.print("  Run: [cyan]pip install git-filter-repo[/]")
    if sys.platform.startswith("win"):
        console.print("  On Windows, ensure your Python Scripts folder is on PATH.")
        if scripts_hint:
            console.print(f"  Example: [cyan]{scripts_hint}[/]")
    sys.exit(1)


TRAILER_RE = re.compile(r"([A-Za-z-]+-by):\s*(.+?)\s*<([^>]+)>", re.IGNORECASE)


def identity_matches(name, email, target_emails, target_name):
    if email and email.lower() in target_emails:
        return True
    if name and target_name and name.lower() == target_name.lower():
        return True
    return False


# ── identity collection ───────────────────────────────────────────────────────

def collect_my_identity():
    """Prompt the user for their name, email, and optional GitHub username."""
    console.print(Panel(
        "[bold]Your Identity[/]\n\n"
        "[dim]Used as the replacement identity for contributor rewrites\n"
        "and as the author for backdated streak commits.[/]",
        style="cyan",
        box=box.ROUNDED,
        padding=(1, 3),
    ))
    console.print()

    name = questionary.text("Your full name:", style=Q_STYLE).ask()
    if not name or not name.strip():
        console.print("[red]✗ Name is required.[/]")
        sys.exit(1)

    email = questionary.text("Your email address:", style=Q_STYLE).ask()
    if not email or not email.strip():
        console.print("[red]✗ Email is required.[/]")
        sys.exit(1)

    username = questionary.text(
        "Your GitHub username (optional — helps detect aliases in history):",
        default="",
        style=Q_STYLE,
    ).ask() or ""

    console.print()
    return UserIdentity(name=name.strip(), username=username.strip(), email=email.strip())


# ── contributor helpers ───────────────────────────────────────────────────────

def collect_contributors(repo):
    """{ display_key : {"emails": set, "name": str, "commits": int} }"""
    people = defaultdict(lambda: {"emails": set(), "name": "", "commits": 0})

    log = run(["git", "log", "--all", "--format=%aN%x00%aE%x00%cN%x00%cE"], repo)
    for line in log.splitlines():
        parts = line.split("\x00")
        if len(parts) < 4:
            continue
        for name, email in [(parts[0].strip(), parts[1].strip()),
                            (parts[2].strip(), parts[3].strip())]:
            if name and email:
                key = f"{name} <{email}>"
                people[key]["name"] = name
                people[key]["emails"].add(email.lower())
                people[key]["commits"] += 1

    body = run(["git", "log", "--all", "--format=%B%x00"], repo)
    for m in TRAILER_RE.finditer(body):
        name, email = m.group(2).strip(), m.group(3).strip()
        key = f"{name} <{email}>"
        people[key]["name"] = name
        people[key]["emails"].add(email.lower())

    return dict(people)


def count_selected_normalization_commits(repo, target_emails, target_names):
    emails_lc = {e.lower() for e in target_emails}
    names_lc = {n.lower() for n in target_names if n}

    log = run([
        "git", "log", "--all",
        "--format=%aN%x00%aE%x00%cN%x00%cE%x00%B%x00---COMMIT_END---"
    ], repo)
    count = 0
    for block in log.split("---COMMIT_END---"):
        parts = block.strip().split("\x00")
        if len(parts) < 4:
            continue

        aname, aemail, cname, cemail = [p.strip() for p in parts[:4]]
        body = "\x00".join(parts[4:]) if len(parts) > 4 else ""

        hit = (
            aemail.lower() in emails_lc
            or cemail.lower() in emails_lc
            or aname.lower() in names_lc
            or cname.lower() in names_lc
        )

        if not hit:
            for m in TRAILER_RE.finditer(body):
                trailer_name = m.group(2).strip().lower()
                trailer_email = m.group(3).strip().lower()
                if trailer_email in emails_lc or trailer_name in names_lc:
                    hit = True
                    break

        if hit:
            count += 1

    return count


def get_zero_commit_contributors(people):
    zero = []
    for key, info in people.items():
        if info["commits"] == 0:
            zero.append({"key": key, "name": info["name"], "emails": set(info["emails"])})
    return zero


def count_zero_replacement_commits(repo, targets):
    target_emails = set()
    target_names = set()
    for item in targets:
        target_emails.update(e.lower() for e in item["emails"])
        target_names.add(item["name"].lower())

    log = run(["git", "log", "--all", "--format=%B%x00---COMMIT_END---"], repo)
    count = 0
    for block in log.split("---COMMIT_END---"):
        body = block.strip()
        if not body:
            continue
        hit = False
        for m in TRAILER_RE.finditer(body):
            trailer_name = m.group(2).strip().lower()
            trailer_email = m.group(3).strip().lower()
            if trailer_email in target_emails or trailer_name in target_names:
                hit = True
                break
        if hit:
            count += 1
    return count


def get_my_aliases(people, me):
    """Find all names in history that share my email or username."""
    aliases = set()
    for info in people.values():
        if me.email.lower() in {e.lower() for e in info["emails"]} and info["name"]:
            aliases.add(info["name"])
    if me.username:
        aliases.add(me.username)
    aliases.discard(me.name)
    return sorted(aliases, key=str.lower)


def count_my_normalization_commits(repo, target_names, me):
    names_lc = {n.lower() for n in target_names}
    email_lc = me.email.lower()

    log = run([
        "git", "log", "--all",
        "--format=%aN%x00%aE%x00%cN%x00%cE%x00%B%x00---COMMIT_END---"
    ], repo)

    count = 0
    for block in log.split("---COMMIT_END---"):
        parts = block.strip().split("\x00")
        if len(parts) < 4:
            continue

        aname, aemail, cname, cemail = [p.strip() for p in parts[:4]]
        body = "\x00".join(parts[4:]) if len(parts) > 4 else ""

        hit = (
            aemail.lower() == email_lc
            or cemail.lower() == email_lc
            or aname.lower() in names_lc
            or cname.lower() in names_lc
        )

        if not hit:
            for m in TRAILER_RE.finditer(body):
                trailer_name = m.group(2).strip().lower()
                trailer_email = m.group(3).strip().lower()
                if trailer_email == email_lc or trailer_name in names_lc:
                    hit = True
                    break

        if hit:
            count += 1

    return count


# ── rewrite callbacks ─────────────────────────────────────────────────────────

def make_callback(target_emails, target_name):
    """
    git-filter-repo commit callback that:
      - Drops commits where the target is sole author AND committer.
      - Strips the target's identity from co-authored commits.
      - Removes all *-by trailers belonging to the target.
    """
    emails_repr = repr({e.lower() for e in target_emails})
    name_repr   = repr(target_name.lower())

    return f"""\
import re as _re

_EMAILS = {emails_repr}
_NAME   = {name_repr}
_TRAILER_RE = _re.compile(rb"^([A-Za-z-]+-by):\\s*(.+?)\\s*<([^>]+)>\\s*$", _re.IGNORECASE)

def _is_target(nb, eb):
    return (
        eb.decode("utf-8", "replace").lower() in _EMAILS
        or nb.decode("utf-8", "replace").lower() == _NAME
    )

def _strip_target_trailers(msg):
    text = msg.decode("utf-8", "replace")
    kept = []
    for line in text.splitlines():
        m = _TRAILER_RE.match(line.encode("utf-8", "replace"))
        if not m:
            kept.append(line)
            continue
        trailer_name = m.group(2).decode("utf-8", "replace").strip().lower()
        trailer_email = m.group(3).decode("utf-8", "replace").strip().lower()
        if trailer_email in _EMAILS or (_NAME and trailer_name == _NAME):
            continue
        kept.append(line)
    cleaned = "\\n".join(kept).strip()
    return cleaned.encode("utf-8")

author_is_target    = _is_target(commit.author_name,    commit.author_email)
committer_is_target = _is_target(commit.committer_name, commit.committer_email)

if commit.message:
    commit.message = _strip_target_trailers(commit.message)

if author_is_target and committer_is_target:
    commit.skip()
else:
    if author_is_target:
        commit.author_name  = commit.committer_name
        commit.author_email = commit.committer_email
        commit.author_date  = commit.committer_date
    if committer_is_target:
        commit.committer_name  = commit.author_name
        commit.committer_email = commit.author_email
        commit.committer_date  = commit.author_date
"""


def make_replace_zero_callback(targets, replacement_name, replacement_email):
    target_emails = set()
    target_names = set()
    for item in targets:
        target_emails.update(e.lower() for e in item["emails"])
        target_names.add(item["name"].lower())

    emails_repr     = repr(target_emails)
    names_repr      = repr(target_names)
    repl_name_repr  = repr(replacement_name)
    repl_email_repr = repr(replacement_email)

    return f"""\
import re as _re

_TARGET_EMAILS = {emails_repr}
_TARGET_NAMES = {names_repr}
_REPL_NAME = {repl_name_repr}
_REPL_EMAIL = {repl_email_repr}
_TRAILER_RE = _re.compile(rb"^([A-Za-z-]+-by):\\s*(.+?)\\s*<([^>]+)>\\s*$", _re.IGNORECASE)

def _is_target(name_b, email_b):
    name = name_b.decode("utf-8", "replace").strip().lower()
    email = email_b.decode("utf-8", "replace").strip().lower()
    return email in _TARGET_EMAILS or name in _TARGET_NAMES

def _rewrite_trailers(msg):
    text = msg.decode("utf-8", "replace")
    kept = []
    seen_replacement = False
    for line in text.splitlines():
        m = _TRAILER_RE.match(line.encode("utf-8", "replace"))
        if not m:
            kept.append(line)
            continue
        trailer_key   = m.group(1).decode("utf-8", "replace")
        trailer_name  = m.group(2)
        trailer_email = m.group(3)
        if _is_target(trailer_name, trailer_email):
            new_line = f"{{trailer_key}}: {{_REPL_NAME}} <{{_REPL_EMAIL}}>"
            if new_line not in kept:
                kept.append(new_line)
                seen_replacement = True
            continue
        current_line = line.strip()
        if current_line.lower() == f"{{trailer_key}}: {{_REPL_NAME}} <{{_REPL_EMAIL}}>".lower():
            if seen_replacement:
                continue
            seen_replacement = True
        kept.append(line)
    cleaned = "\\n".join(kept).strip()
    return cleaned.encode("utf-8")

if commit.message:
    commit.message = _rewrite_trailers(commit.message)
"""


def make_normalize_me_callback(target_names, me):
    names_repr      = repr({n.lower() for n in target_names})
    repl_name_repr  = repr(me.name)
    repl_email_repr = repr(me.email)

    return f"""\
import re as _re

_TARGET_NAMES = {names_repr}
_TARGET_EMAIL = {repr(me.email.lower())}
_REPL_NAME = {repl_name_repr}
_REPL_EMAIL = {repl_email_repr}
_TRAILER_RE = _re.compile(rb"^([A-Za-z-]+-by):\\s*(.+?)\\s*<([^>]+)>\\s*$", _re.IGNORECASE)

def _is_target(name_b, email_b):
    name = name_b.decode("utf-8", "replace").strip().lower()
    email = email_b.decode("utf-8", "replace").strip().lower()
    return email == _TARGET_EMAIL or name in _TARGET_NAMES

def _rewrite_trailers(msg):
    text = msg.decode("utf-8", "replace")
    kept = []
    seen_lines = set()
    for line in text.splitlines():
        m = _TRAILER_RE.match(line.encode("utf-8", "replace"))
        if not m:
            kept.append(line)
            continue
        trailer_key   = m.group(1).decode("utf-8", "replace")
        trailer_name  = m.group(2)
        trailer_email = m.group(3)
        if _is_target(trailer_name, trailer_email):
            line = f"{{trailer_key}}: {{_REPL_NAME}} <{{_REPL_EMAIL}}>"
        line_key = line.strip().lower()
        if line_key in seen_lines:
            continue
        seen_lines.add(line_key)
        kept.append(line)
    cleaned = "\\n".join(kept).strip()
    return cleaned.encode("utf-8")

if _is_target(commit.author_name, commit.author_email):
    commit.author_name = _REPL_NAME.encode("utf-8")
    commit.author_email = _REPL_EMAIL.encode("utf-8")

if _is_target(commit.committer_name, commit.committer_email):
    commit.committer_name = _REPL_NAME.encode("utf-8")
    commit.committer_email = _REPL_EMAIL.encode("utf-8")

if commit.message:
    commit.message = _rewrite_trailers(commit.message)
"""


def make_replace_identity_callback(target_emails, target_names, replacement_name, replacement_email):
    emails_repr     = repr({e.lower() for e in target_emails})
    names_repr      = repr({n.lower() for n in target_names if n})
    repl_name_repr  = repr(replacement_name)
    repl_email_repr = repr(replacement_email)

    return f"""\
import re as _re

_TARGET_EMAILS = {emails_repr}
_TARGET_NAMES = {names_repr}
_REPL_NAME = {repl_name_repr}
_REPL_EMAIL = {repl_email_repr}
_TRAILER_RE = _re.compile(rb"^([A-Za-z-]+-by):\\s*(.+?)\\s*<([^>]+)>\\s*$", _re.IGNORECASE)

def _is_target(name_b, email_b):
    name = name_b.decode("utf-8", "replace").strip().lower()
    email = email_b.decode("utf-8", "replace").strip().lower()
    return email in _TARGET_EMAILS or name in _TARGET_NAMES

def _rewrite_trailers(msg):
    text = msg.decode("utf-8", "replace")
    kept = []
    seen_lines = set()
    for line in text.splitlines():
        m = _TRAILER_RE.match(line.encode("utf-8", "replace"))
        if not m:
            kept.append(line)
            continue
        trailer_key   = m.group(1).decode("utf-8", "replace")
        trailer_name  = m.group(2)
        trailer_email = m.group(3)
        if _is_target(trailer_name, trailer_email):
            line = f"{{trailer_key}}: {{_REPL_NAME}} <{{_REPL_EMAIL}}>"
        line_key = line.strip().lower()
        if line_key in seen_lines:
            continue
        seen_lines.add(line_key)
        kept.append(line)
    cleaned = "\\n".join(kept).strip()
    return cleaned.encode("utf-8")

if _is_target(commit.author_name, commit.author_email):
    commit.author_name = _REPL_NAME.encode("utf-8")
    commit.author_email = _REPL_EMAIL.encode("utf-8")

if _is_target(commit.committer_name, commit.committer_email):
    commit.committer_name = _REPL_NAME.encode("utf-8")
    commit.committer_email = _REPL_EMAIL.encode("utf-8")

if commit.message:
    commit.message = _rewrite_trailers(commit.message)
"""


# ── rewrite runners ───────────────────────────────────────────────────────────

def rewrite_history(repo, emails, name, filter_repo_cmd):
    callback = make_callback(emails, name)
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console, transient=True) as progress:
        progress.add_task("Rewriting history…", total=None)
        r = subprocess.run(
            filter_repo_cmd + ["--force", "--commit-callback", callback],
            cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
    if r.returncode != 0:
        console.print(f"\n[bold red]✗ filter-repo failed:[/]\n{r.stderr.strip()}")
        sys.exit(1)


def rewrite_zero_contributors(repo, targets, replacement_name, replacement_email, filter_repo_cmd):
    callback = make_replace_zero_callback(targets, replacement_name, replacement_email)
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console, transient=True) as progress:
        progress.add_task("Rewriting zero-commit contributor trailers…", total=None)
        r = subprocess.run(
            filter_repo_cmd + ["--force", "--commit-callback", callback],
            cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
    if r.returncode != 0:
        console.print(f"\n[bold red]✗ filter-repo failed:[/]\n{r.stderr.strip()}")
        sys.exit(1)


def normalize_me_identity(repo, target_names, filter_repo_cmd, me):
    callback = make_normalize_me_callback(target_names, me)
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console, transient=True) as progress:
        progress.add_task("Normalizing your contributor identity…", total=None)
        r = subprocess.run(
            filter_repo_cmd + ["--force", "--commit-callback", callback],
            cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
    if r.returncode != 0:
        console.print(f"\n[bold red]✗ filter-repo failed:[/]\n{r.stderr.strip()}")
        sys.exit(1)


def normalize_selected_contributor(repo, target_emails, target_names, filter_repo_cmd, me):
    callback = make_replace_identity_callback(target_emails, target_names, me.name, me.email)
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console, transient=True) as progress:
        progress.add_task("Normalizing selected contributor to your identity…", total=None)
        r = subprocess.run(
            filter_repo_cmd + ["--force", "--commit-callback", callback],
            cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
    if r.returncode != 0:
        console.print(f"\n[bold red]✗ filter-repo failed:[/]\n{r.stderr.strip()}")
        sys.exit(1)


def run_gc(repo):
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console, transient=True) as progress:
        progress.add_task("Cleaning up…", total=None)
        subprocess.run(
            ["git", "gc", "--prune=now", "--aggressive"],
            cwd=repo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )


# ── GitHub contribution streak helpers ────────────────────────────────────────

def fetch_github_contributions(username, token, from_date, to_date):
    """Returns {date_str: contribution_count} via GitHub GraphQL API (needs read:user scope)."""
    query = """
    query($username: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $username) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            weeks {
              contributionDays {
                contributionCount
                date
              }
            }
          }
        }
      }
    }
    """
    headers = {
        "Authorization": f"bearer {token}",
        "Content-Type":  "application/json",
    }
    payload = {
        "query":     query,
        "variables": {
            "username": username,
            "from":     from_date.strftime("%Y-%m-%dT00:00:00Z"),
            "to":       to_date.strftime("%Y-%m-%dT23:59:59Z"),
        },
    }

    try:
        resp = requests.post(GITHUB_GRAPHQL_URL, json=payload, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.HTTPError as e:
        console.print(f"[bold red]✗ GitHub API HTTP error:[/] {e}")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]✗ Network error:[/] {e}")
        sys.exit(1)

    if "errors" in data:
        msgs = "; ".join(e.get("message", str(e)) for e in data["errors"])
        console.print(f"[bold red]✗ GitHub GraphQL error:[/] {msgs}")
        sys.exit(1)

    user_data = data.get("data", {}).get("user")
    if not user_data:
        console.print(f"[bold red]✗ GitHub user not found:[/] {username}")
        sys.exit(1)

    calendar = user_data["contributionsCollection"]["contributionCalendar"]
    result = {}
    for week in calendar["weeks"]:
        for day in week["contributionDays"]:
            result[day["date"]] = day["contributionCount"]
    return result


def get_repo_date_range(repo):
    """Returns (first_commit_date, last_commit_date) across all branches, or (None, None)."""
    try:
        first_raw = run(["git", "log", "--all", "--reverse", "--format=%aI"], repo).strip().splitlines()
        last_raw  = run(["git", "log", "--all", "--format=%aI"], repo).strip().splitlines()
    except SystemExit:
        return None, None

    def parse_iso(s):
        s = s.strip()
        if not s:
            return None
        try:
            return datetime.datetime.fromisoformat(s).date()
        except ValueError:
            return None

    return (
        parse_iso(first_raw[0]) if first_raw else None,
        parse_iso(last_raw[0])  if last_raw  else None,
    )


def find_missing_days(contributions, from_date, to_date, max_count=1):
    """Returns sorted dates in [from_date, to_date] with <= max_count contributions.
    Default of 1 catches both empty days and days from a prior single-commit pass."""
    today = datetime.date.today()
    effective_to = min(to_date, today)
    missing = []
    current = from_date
    while current <= effective_to:
        if contributions.get(current.strftime("%Y-%m-%d"), 0) <= max_count:
            missing.append(current)
        current += datetime.timedelta(days=1)
    return missing


def select_days_to_fill(missing_days, pct):
    """Randomly select pct% of missing_days, returned sorted."""
    n = max(1, round(len(missing_days) * pct / 100))
    n = min(n, len(missing_days))
    return sorted(random.sample(missing_days, n))


def show_contribution_summary(contributions, missing_days, to_fill):
    """Month-by-month table: contributions, days needing fill, days that will be filled."""
    by_month = defaultdict(lambda: {"total": 0, "missing": 0, "fill": 0})

    for date_str, count in contributions.items():
        by_month[date_str[:7]]["total"] += count

    to_fill_set = {d.strftime("%Y-%m-%d") for d in to_fill}
    for date in missing_days:
        ym = date.strftime("%Y-%m")
        by_month[ym]["missing"] += 1
        if date.strftime("%Y-%m-%d") in to_fill_set:
            by_month[ym]["fill"] += 1

    table = Table(box=box.SIMPLE_HEAVY, header_style="bold cyan", padding=(0, 1),
                  title="Contribution Calendar Summary")
    table.add_column("Month",         style="bold white",  min_width=9)
    table.add_column("Contributions", style="green",       justify="right", min_width=13)
    table.add_column("Needs Fill",    style="red",         justify="right", min_width=12)
    table.add_column("Will Fill",     style="yellow bold", justify="right", min_width=10)

    for ym in sorted(by_month):
        info = by_month[ym]
        table.add_row(
            ym,
            str(info["total"]),
            str(info["missing"]) if info["missing"] > 0 else "[dim]0[/]",
            str(info["fill"])    if info["fill"]    > 0 else "[dim]0[/]",
        )
    console.print(table)


def collect_repo_commit_messages(repo):
    """Deduplicated commit subjects from full history, excluding merges and trailers."""
    raw = run(["git", "log", "--all", "--format=%s"], repo)
    seen = set()
    messages = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("merge "):
            continue
        if TRAILER_RE.match(line):
            continue
        if line not in seen:
            seen.add(line)
            messages.append(line)
    return messages


def create_backdated_commits(repo, dates, messages, me):
    """
    Create git --allow-empty commits with backdated dates.

    Per day: 1–5 commits (weighted toward lower counts) at random times
    between 8 AM and 11 PM. Each commit gets a randomly sampled message.
    """
    COMMIT_COUNT_WEIGHTS = [30, 25, 20, 15, 10]  # weights for counts 1–5

    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"]     = me.name
    env["GIT_AUTHOR_EMAIL"]    = me.email
    env["GIT_COMMITTER_NAME"]  = me.name
    env["GIT_COMMITTER_EMAIL"] = me.email

    created = 0
    failed  = 0

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console, transient=True) as progress:
        progress.add_task(f"Creating commits across {len(dates)} day(s)…", total=None)

        for date in dates:
            n_commits = random.choices(range(1, 6), weights=COMMIT_COUNT_WEIGHTS)[0]
            minutes_pool = sorted(random.sample(range(8 * 60, 23 * 60), n_commits))

            for minutes in minutes_pool:
                hour, minute = divmod(minutes, 60)
                date_str = f"{date.strftime('%Y-%m-%d')}T{hour:02d}:{minute:02d}:00+0000"
                commit_env = env.copy()
                commit_env["GIT_AUTHOR_DATE"]    = date_str
                commit_env["GIT_COMMITTER_DATE"] = date_str

                r = subprocess.run(
                    ["git", "commit", "--allow-empty", "-m", random.choice(messages)],
                    cwd=repo, env=commit_env,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                if r.returncode == 0:
                    created += 1
                else:
                    failed += 1

    return created, failed


def _execute_fill(repo, username, token, from_date, to_date, pct, commit_messages, me):
    """
    Core fill logic for one date range: fetch calendar, find gaps, confirm, create commits.
    Returns True if commits were created.
    """
    today = datetime.date.today()

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console, transient=True) as p:
        p.add_task("Fetching GitHub contribution calendar…", total=None)
        contributions = fetch_github_contributions(username, token, from_date, to_date)

    total_days   = (min(to_date, today) - from_date).days + 1
    days_with    = sum(1 for d, c in contributions.items()
                       if c > 0 and from_date <= datetime.date.fromisoformat(d) <= min(to_date, today))
    missing_days = find_missing_days(contributions, from_date, to_date)

    console.print(f"[dim]Window    :[/] {from_date} → {min(to_date, today)} ({total_days} days)")
    console.print(f"[dim]Active    :[/] [green]{days_with}[/] day(s) with contributions")
    console.print(f"[dim]Needs fill:[/] [red]{len(missing_days)}[/] day(s) with 0 or 1 contribution(s)\n")

    if not missing_days:
        console.print("[bold green]✓  No missing days in this range — streak intact![/]")
        return False

    to_fill = select_days_to_fill(missing_days, pct)

    show_contribution_summary(contributions, missing_days, to_fill)
    console.print()

    preview_limit = 15
    console.print(f"[dim]Days to fill:[/] [bold cyan]{len(to_fill)}[/]")
    for d in to_fill[:preview_limit]:
        console.print(f"  [cyan]{d}[/]")
    if len(to_fill) > preview_limit:
        console.print(f"  [dim]… and {len(to_fill) - preview_limit} more[/]")
    console.print()

    console.print(Panel(
        f"[bold yellow]⚠  This will add commits to the current branch[/]\n\n"
        f"  Repo    : [bold white]{repo}[/]\n"
        f"  Author  : [bold white]{me.name} <{me.email}>[/]\n"
        f"  Range   : [cyan]{to_fill[0]} → {to_fill[-1]}[/]\n"
        f"  Days    : [yellow]{len(to_fill)} day(s) → ~{len(to_fill)}–{len(to_fill) * 5} commits (randomized)[/]\n"
        f"  Messages: [dim]randomly sampled from {len(commit_messages)} repo subject(s)[/]\n\n"
        f"  [dim]Push afterwards with:[/]\n"
        f"  [cyan]git push[/]",
        title="[bold yellow] Confirm [/]",
        style="yellow",
        box=box.ROUNDED,
        padding=(1, 3),
    ))

    proceed = questionary.confirm(
        "Create these commits?",
        default=False,
        style=Q_STYLE,
        auto_enter=False,
    ).ask()
    if not proceed:
        console.print("[dim]Aborted.[/]")
        return False

    console.print()
    created, failed = create_backdated_commits(repo, to_fill, commit_messages, me)

    if failed:
        console.print(f"[yellow]⚠[/] {failed} commit(s) failed to create.")

    console.print(Panel(
        f"[bold green]✓  {created} commit(s) created.[/]\n\n"
        "[bold]Next steps:[/]\n\n"
        f"  [cyan]git log --oneline -{min(created + 3, 20)}[/]   ← verify\n"
        f"  [cyan]git push[/]                        ← publish to GitHub\n\n"
        "  [dim]Contributions can take a few minutes to appear on your profile.[/]",
        style="green",
        box=box.ROUNDED,
        padding=(1, 3),
    ))
    return True


def _prompt_date(label, default):
    """Prompt for a YYYY-MM-DD date string, returning a date object."""
    raw = questionary.text(label, default=str(default), style=Q_STYLE).ask()
    if not raw:
        return None
    try:
        return datetime.date.fromisoformat(raw.strip())
    except ValueError:
        console.print("[red]✗ Invalid date — use YYYY-MM-DD format.[/]")
        return None


def fill_streaks_flow(repo, me):
    """Interactive flow: fetch GitHub calendar → pick % of missing days → create commits.
    After each pass, offers to run another pass for a different date range."""
    console.print(Panel(
        "[bold]Fill Missing GitHub Contribution Days[/]\n\n"
        "[dim]Reads your GitHub contribution calendar and creates backdated\n"
        "commits on missing days to restore your streak.[/]",
        style="cyan",
        box=box.ROUNDED,
        padding=(1, 3),
    ))
    console.print()

    # 1. GitHub credentials
    username = questionary.text("GitHub username:", style=Q_STYLE).ask()
    if not username:
        console.print("[dim]Aborted.[/]")
        return

    token = questionary.password(
        "GitHub personal access token (needs 'read:user' scope):",
        style=Q_STYLE,
    ).ask()
    if not token:
        console.print("[dim]Aborted.[/]")
        return

    # 2. Collect commit messages once — reused across all passes
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console, transient=True) as p:
        p.add_task("Sampling commit messages from repo history…", total=None)
        commit_messages = collect_repo_commit_messages(repo)

    if not commit_messages:
        commit_messages = ["Update"]

    console.print(f"[dim]Message pool:[/] [cyan]{len(commit_messages)}[/] unique subject(s) from repo history\n")

    # 3. Pick percentage — reused across all passes
    def validate_pct(v):
        return True if v.isdigit() and 1 <= int(v) <= 100 else "Enter a whole number between 1 and 100"

    pct_str = questionary.text(
        "Percentage of missing days to fill (1–100):",
        default="100",
        validate=validate_pct,
        style=Q_STYLE,
    ).ask()
    if not pct_str:
        console.print("[dim]Aborted.[/]")
        return
    pct = int(pct_str)

    # 4. Determine default window
    today = datetime.date.today()
    first_date, last_date = get_repo_date_range(repo)
    default_from = today - datetime.timedelta(days=364)
    if first_date:
        default_from = max(default_from, first_date)
        console.print(f"[dim]Repo commit range: {first_date} → {last_date or today}[/]\n")

    pass_num = 1
    while True:
        console.rule(f"[bold cyan]Pass {pass_num}[/]")
        console.print()

        # Date range for this pass
        use_default = questionary.confirm(
            f"Use default window ({default_from} → {today})?",
            default=True,
            style=Q_STYLE,
            auto_enter=False,
        ).ask()
        if use_default is None:
            console.print("[dim]Aborted.[/]")
            return

        if use_default:
            from_date = default_from
            to_date   = today
        else:
            from_date = _prompt_date("From date (YYYY-MM-DD):", default_from)
            if not from_date:
                return
            to_date = _prompt_date("To date   (YYYY-MM-DD):", today)
            if not to_date:
                return
            if from_date > to_date:
                console.print("[red]✗ From-date must be before to-date.[/]")
                return

        _execute_fill(repo, username, token, from_date, to_date, pct, commit_messages, me)

        # Offer another pass
        console.print()
        again = questionary.confirm(
            "Run another pass for a different date range?",
            default=False,
            style=Q_STYLE,
            auto_enter=False,
        ).ask()
        if not again:
            break
        pass_num += 1
        console.print()


# ── UI helpers ────────────────────────────────────────────────────────────────

def header():
    console.print()
    t = Text()
    t.append("  ☠  ", style="bold red")
    t.append("git contributor eraser", style="bold white")
    t.append("  ☠  ", style="bold red")
    console.print(Panel(t, style="dim", box=box.SIMPLE_HEAD,
                        padding=(0, 4), expand=False))
    console.print()


def pick_repo():
    cwd = str(Path.cwd())
    path_str = questionary.text("Repo path:", default=cwd, style=Q_STYLE).ask()
    if path_str is None:
        sys.exit(0)
    repo = Path(path_str).expanduser().resolve()
    if not repo.is_dir():
        console.print(f"[red]✗ Not a directory:[/] {repo}")
        sys.exit(1)
    if not is_git_repo(repo):
        console.print(f"[red]✗ Not a git repo:[/] {repo}")
        sys.exit(1)
    return repo


def show_table(people):
    table = Table(box=box.SIMPLE_HEAVY, header_style="bold cyan", padding=(0, 1))
    table.add_column("#",        style="dim",        width=4,  justify="right")
    table.add_column("Name",     style="bold white",  min_width=22)
    table.add_column("Email(s)", style="dim cyan",    min_width=28)
    table.add_column("Commits",  style="yellow",      width=9,  justify="right")
    for i, key in enumerate(sorted(people), 1):
        info = people[key]
        table.add_row(str(i), info["name"],
                      ", ".join(sorted(info["emails"])),
                      str(info["commits"]))
    console.print(table)


def pick_contributor(people):
    sorted_keys = sorted(people)
    choices = []
    for k in sorted_keys:
        info = people[k]
        label = (f"{info['name']}  "
                 f"[{', '.join(sorted(info['emails']))}]  "
                 f"({info['commits']} commit{'s' if info['commits'] != 1 else ''})")
        choices.append(questionary.Choice(title=label, value=k))
    choices.append(questionary.Choice(title="── Cancel ──", value=None))
    return questionary.select(
        "Select contributor:",
        choices=choices,
        style=Q_STYLE,
        use_indicator=True,
    ).ask()


def confirm_erase(target_key, emails, affected):
    console.print()
    console.print(Panel(
        f"[bold red]⚠  DESTRUCTIVE — CANNOT BE UNDONE[/]\n\n"
        f"  Target  : [bold white]{target_key}[/]\n"
        f"  Emails  : [dim]{', '.join(sorted(emails))}[/]\n"
        f"  Commits : [yellow]{affected} will be rewritten or dropped[/]\n\n"
        f"  [dim]Sole-author commits are dropped entirely.\n"
        f"  Co-authored commits have the identity removed.\n"
        f"  All Co-authored-by trailers for this person are stripped.\n"
        f"  All branches and tags are rewritten.[/]",
        title="[bold red] Confirm [/]",
        style="red",
        box=box.ROUNDED,
        padding=(1, 3),
    ))
    return questionary.confirm(
        "Erase this contributor?",
        default=False,
        style=Q_STYLE,
        auto_enter=False,
    ).ask()


def confirm_normalize(target_key, emails, affected, me):
    me_label = f"{me.name}{' (' + me.username + ')' if me.username else ''} <{me.email}>"
    console.print()
    console.print(Panel(
        f"[bold red]⚠  DESTRUCTIVE — CANNOT BE UNDONE[/]\n\n"
        f"  Action  : [bold white]Normalize selected contributor to your identity[/]\n"
        f"  Target  : [bold white]{target_key}[/]\n"
        f"  Emails  : [dim]{', '.join(sorted(emails))}[/]\n"
        f"  Replace : [bold white]{me_label}[/]\n"
        f"  Commits : [yellow]{affected} will be rewritten[/]\n\n"
        f"  [dim]Author/committer and *-by trailer identities are normalized.\n"
        f"  All branches and tags are rewritten.[/]",
        title="[bold red] Confirm [/]",
        style="red",
        box=box.ROUNDED,
        padding=(1, 3),
    ))
    return questionary.confirm(
        "Normalize this contributor to your profile?",
        default=False,
        style=Q_STYLE,
        auto_enter=False,
    ).ask()


def show_done(repo):
    console.print()
    console.print(Panel(
        "[bold green]✓  Done.[/]\n\n"
        "[bold]Recommended next steps:[/]\n\n"
        f"  [cyan]git log --all --oneline[/]   ← verify\n"
        f"  [cyan]git push --force --all[/]\n"
        f"  [cyan]git push --force --tags[/]\n\n"
        "  [dim]All collaborators must re-clone — their history is now diverged.[/]",
        style="green",
        box=box.ROUNDED,
        padding=(1, 3),
    ))


# ── action flows ──────────────────────────────────────────────────────────────

def replace_zero_flow(repo, people, filter_repo_cmd, me):
    zero = get_zero_commit_contributors(people)
    if not zero:
        console.print("[yellow]No contributors with 0 commits were found.[/]")
        return

    zero_keys = [item["key"] for item in sorted(zero, key=lambda x: x["key"].lower())]
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console, transient=True) as p:
        p.add_task("Counting affected commits…", total=None)
        affected = count_zero_replacement_commits(repo, zero)

    me_label = f"{me.name}{' (' + me.username + ')' if me.username else ''} <{me.email}>"
    console.print()
    console.print(Panel(
        f"[bold red]⚠  DESTRUCTIVE — CANNOT BE UNDONE[/]\n\n"
        f"  Action  : [bold white]Replace zero-commit contributor trailers[/]\n"
        f"  Replace : [dim]{len(zero)} contributor(s)[/]\n"
        f"  With    : [bold white]{me_label}[/]\n"
        f"  Commits : [yellow]{affected} will be rewritten[/]\n\n"
        f"  [dim]Targets:\n    - {chr(10).join('    - ' + k for k in zero_keys)}\n\n"
        f"  Only *-by trailer identities are replaced.\n"
        f"  All branches and tags are rewritten.[/]",
        title="[bold red] Confirm [/]",
        style="red",
        box=box.ROUNDED,
        padding=(1, 3),
    ))

    proceed = questionary.confirm(
        "Proceed with zero-commit replacement?",
        default=False,
        style=Q_STYLE,
        auto_enter=False,
    ).ask()
    if not proceed:
        console.print("[dim]Aborted.[/]")
        return

    console.print()
    rewrite_zero_contributors(repo, zero, me.name, me.email, filter_repo_cmd)
    console.print("[green]✓[/] History rewritten.")
    run_gc(repo)
    console.print("[green]✓[/] Repo cleaned.")
    show_done(repo)


def normalize_me_flow(repo, people, filter_repo_cmd, me):
    aliases = get_my_aliases(people, me)
    targets = sorted(set(aliases + [me.name] + ([me.username] if me.username else [])), key=str.lower)

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console, transient=True) as p:
        p.add_task("Counting affected commits…", total=None)
        affected = count_my_normalization_commits(repo, targets, me)

    alias_lines = "\n    - ".join(aliases) if aliases else "(none found; email-based rewrite only)"
    me_label = f"{me.name}{' (' + me.username + ')' if me.username else ''} <{me.email}>"
    console.print()
    console.print(Panel(
        f"[bold red]⚠  DESTRUCTIVE — CANNOT BE UNDONE[/]\n\n"
        f"  Action  : [bold white]Consolidate duplicate profiles to one identity[/]\n"
        f"  Keep    : [bold white]{me_label}[/]\n"
        f"  Commits : [yellow]{affected} will be rewritten[/]\n\n"
        f"  [dim]Detected aliases:\n"
        f"    - {alias_lines}\n\n"
        f"  Author/committer and *-by trailer identities will be normalized.\n"
        f"  All branches and tags are rewritten.[/]",
        title="[bold red] Confirm [/]",
        style="red",
        box=box.ROUNDED,
        padding=(1, 3),
    ))

    proceed = questionary.confirm(
        "Proceed with profile consolidation?",
        default=False,
        style=Q_STYLE,
        auto_enter=False,
    ).ask()
    if not proceed:
        console.print("[dim]Aborted.[/]")
        return

    console.print()
    normalize_me_identity(repo, targets, filter_repo_cmd, me)
    console.print("[green]✓[/] History rewritten.")
    run_gc(repo)
    console.print("[green]✓[/] Repo cleaned.")
    show_done(repo)


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Erase or replace contributor identities in git history, "
                    "or fill missing GitHub contribution days with backdated commits."
    )
    parser.add_argument(
        "repo",
        nargs="?",
        help="Path to git repository (defaults to interactive prompt)",
    )
    parser.add_argument(
        "--replace-zero-with-me",
        action="store_true",
        help="Replace all zero-commit trailer contributors with your identity",
    )
    parser.add_argument(
        "--normalize-me",
        action="store_true",
        help="Consolidate your own duplicate aliases/profiles into one identity",
    )
    parser.add_argument(
        "--fill-streaks",
        action="store_true",
        help="Fill missing GitHub contribution days with backdated empty commits",
    )
    return parser.parse_args()


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    header()

    args = parse_args()

    # 1. Repo
    repo = Path(args.repo).expanduser().resolve() if args.repo else pick_repo()
    if not repo.is_dir() or not is_git_repo(repo):
        console.print(f"[red]✗ Invalid repo:[/] {repo}")
        sys.exit(1)

    console.print(f"[dim]Repo:[/] [bold]{repo}[/]\n")

    # 2. Collect identity (needed by all actions)
    me = collect_my_identity()

    # fill-streaks doesn't need contributor scanning — handle it early
    if args.fill_streaks:
        fill_streaks_flow(repo, me)
        sys.exit(0)

    filter_repo_cmd = get_filter_repo_cmd(repo)

    # 3. Scan contributors
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console, transient=True) as p:
        p.add_task("Scanning all branches…", total=None)
        people = collect_contributors(repo)

    if not people:
        console.print("[yellow]No contributors found.[/]")
        sys.exit(0)

    console.print(f"[dim]Found[/] [bold cyan]{len(people)}[/] [dim]contributor(s)[/]\n")
    show_table(people)

    if args.replace_zero_with_me:
        replace_zero_flow(repo, people, filter_repo_cmd, me)
        sys.exit(0)

    if args.normalize_me:
        normalize_me_flow(repo, people, filter_repo_cmd, me)
        sys.exit(0)

    # 4. Interactive action menu
    action = questionary.select(
        "What would you like to do?",
        choices=[
            questionary.Choice("Normalize a contributor to my identity",      value="normalize"),
            questionary.Choice("Erase a contributor from history entirely",   value="erase"),
            questionary.Choice("Replace zero-commit trailer authors with me", value="replace_zero"),
            questionary.Choice("Consolidate my own duplicate identities",     value="normalize_me"),
            questionary.Choice("Fill missing GitHub contribution days",       value="fill_streaks"),
            questionary.Choice("── Cancel ──",                                value=None),
        ],
        style=Q_STYLE,
        use_indicator=True,
    ).ask()

    if not action:
        console.print("[dim]Cancelled.[/]")
        sys.exit(0)

    if action == "fill_streaks":
        fill_streaks_flow(repo, me)
        sys.exit(0)

    if action == "replace_zero":
        replace_zero_flow(repo, people, filter_repo_cmd, me)
        sys.exit(0)

    if action == "normalize_me":
        normalize_me_flow(repo, people, filter_repo_cmd, me)
        sys.exit(0)

    # 5. Pick contributor (for normalize or erase)
    target_key = pick_contributor(people)
    if not target_key:
        console.print("[dim]Cancelled.[/]")
        sys.exit(0)

    info   = people[target_key]
    emails = info["emails"]
    name   = info["name"]

    # 6. Count affected commits
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console, transient=True) as p:
        p.add_task("Counting affected commits…", total=None)
        affected = count_selected_normalization_commits(repo, emails, {name})

    # 7. Confirm + rewrite
    if action == "erase":
        if not confirm_erase(target_key, emails, affected):
            console.print("[dim]Aborted.[/]")
            sys.exit(0)
        console.print()
        rewrite_history(repo, emails, name, filter_repo_cmd)
    else:  # normalize
        if not confirm_normalize(target_key, emails, affected, me):
            console.print("[dim]Aborted.[/]")
            sys.exit(0)
        console.print()
        normalize_selected_contributor(repo, emails, {name}, filter_repo_cmd, me)

    console.print("[green]✓[/] History rewritten.")
    run_gc(repo)
    console.print("[green]✓[/] Repo cleaned.")
    show_done(repo)


if __name__ == "__main__":
    main()
