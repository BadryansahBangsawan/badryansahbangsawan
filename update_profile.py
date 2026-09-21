#!/usr/bin/env python3
"""
- Quote of the Day
- GitHub Stats (repos, stars, commits, followers, streaks)
- Languages + expertise from owned-repo linguist bytes

Author: Badryansah Bangsawan
"""

import os
import sys
import json
import time
import hashlib
import requests
import datetime
from zoneinfo import ZoneInfo

from collections import Counter
from dateutil import relativedelta
from lxml import etree


# ============================================================
# Configuration
# ============================================================
GRAPHQL_TOKEN = os.environ.get('ACCESS_TOKEN') or os.environ.get('GITHUB_TOKEN') or ''
HEADERS = {'Authorization': f'token {GRAPHQL_TOKEN}'}
USER_NAME = os.environ.get('USER_NAME', 'BadryansahBangsawan')
USER_TZ = ZoneInfo(os.environ.get('USER_TZ', 'Asia/Jakarta'))
HAS_REPO_TOKEN = bool(os.environ.get('ACCESS_TOKEN'))



QUERY_COUNT = {
    'user_getter': 0, 'follower_getter': 0,
    'graph_repos_stars': 0, 'recursive_loc': 0,
    'graph_commits': 0, 'graph_streak': 0, 'loc_query': 0,
    'graph_languages': 0,
}

# Linguist names that are markup/config, not programming languages.
COMPUTER_LANGS = {
    'HTML', 'CSS', 'SCSS', 'Less', 'JSON', 'SQL', 'PLpgSQL', 'YAML',
    'Markdown', 'Dockerfile', 'Makefile', 'CMake', 'GraphQL', 'TOML',
    'XML', 'SVG', 'Shell', 'PowerShell', 'Batchfile',
}
COMPUTER_CANON = {'PLpgSQL': 'SQL', 'SCSS': 'CSS', 'Less': 'CSS'}
COMPUTER_FALLBACK = ['HTML', 'CSS', 'JSON', 'SQL', 'YAML', 'Markdown']
SKIP_LANGS = {'Inno Setup', 'Objective-C'}
MAX_PROGRAMMING = 4
MAX_COMPUTER = 6


def classify_languages(bytes_by_lang):
    """Split linguist byte totals into programming vs computer language labels."""
    programming = []
    computer_seen = []
    for name, _size in sorted(bytes_by_lang.items(), key=lambda kv: kv[1], reverse=True):
        if name in SKIP_LANGS:
            continue
        if name in COMPUTER_LANGS:
            canon = COMPUTER_CANON.get(name, name)
            if canon not in computer_seen:
                computer_seen.append(canon)
            continue
        if name not in programming:
            programming.append(name)
    ordered = list(COMPUTER_FALLBACK)
    for name in computer_seen:
        if name not in ordered:
            ordered.append(name)
    return programming[:MAX_PROGRAMMING], ordered[:MAX_COMPUTER]


def derive_expertise(programming):
    names = set(programming)
    out = []
    if 'Swift' in names:
        out.append('macOS')
    if names & {'TypeScript', 'JavaScript'}:
        out.append('Fullstack')
    for fallback in ('DevOps', 'Backend', 'Automation'):
        if len(out) >= 3:
            break
        if fallback not in out:
            out.append(fallback)
    return out[:3]


def derive_project(programming):
    if 'Swift' in programming:
        return 'open source, macOS apps'
    return 'open source, automation'


assert classify_languages({
    'TypeScript': 100, 'JavaScript': 80, 'Swift': 60, 'Dart': 40, 'Python': 20,
    'CSS': 10, 'HTML': 5, 'PLpgSQL': 4,
}) == (['TypeScript', 'JavaScript', 'Swift', 'Dart'],
       ['HTML', 'CSS', 'JSON', 'SQL', 'YAML', 'Markdown'])
assert derive_expertise(['TypeScript', 'JavaScript', 'Swift', 'Dart']) == ['macOS', 'Fullstack', 'DevOps']
assert derive_project(['Swift', 'TypeScript']) == 'open source, macOS apps'


# SVG element IDs to update
SVG_ELEMENTS = {
    'age_data': 'age_data',
    'age_data_dots': 'age_data_dots',
    'repo_data': 'repo_data',
    'repo_data_dots': 'repo_data_dots',
    'star_data': 'star_data',
    'star_data_dots': 'star_data_dots',
    'commit_data': 'commit_data',
    'commit_data_dots': 'commit_data_dots',
    'follower_data': 'follower_data',
    'follower_data_dots': 'follower_data_dots',
    'streak_data': 'streak_data',
    'streak_data_dots': 'streak_data_dots',
    'longest_data': 'longest_data',
    'longest_data_dots': 'longest_data_dots',
    'quote_text': 'quote_text',
    'quote_author': 'quote_author',
}


# ============================================================
# Utility Functions
# ============================================================
def format_plural(unit):
    return 's' if unit != 1 else ''


def daily_readme(birthday):
    diff = relativedelta.relativedelta(datetime.datetime.now(datetime.timezone.utc), birthday)
    return f"{diff.years} year{format_plural(diff.years)}, {diff.months} month{format_plural(diff.months)}, {diff.days} day{format_plural(diff.days)}"


def query_count(func_name):
    QUERY_COUNT[func_name] += 1


def graphql_request(func_name, query, variables):
    query_count(func_name)
    resp = requests.post(
        'https://api.github.com/graphql',
        json={'query': query, 'variables': variables},
        headers=HEADERS,
        timeout=30
    )
    if resp.status_code != 200:
        raise Exception(f"{func_name} failed: {resp.status_code} - {resp.text}")
    payload = resp.json()
    if payload.get('data') is None:
        raise Exception(f"{func_name} graphql: {payload.get('errors')}")
    return payload



# ============================================================
# Quote of the Day (api.quotable.io)
# ============================================================
def fetch_quote():
    """Fetch a random short inspirational quote (ideally <40 chars)"""
    best = ("Code is poetry written in logic.", "Anonymous")
    best_len = 999
    attempts = [
        ("https://zenquotes.io/api/random", {}),
        ("https://api.quotable.io/random?tags=technology|inspirational|programming", {}),
        ("https://api.quotable.io/random?tags=technology|inspirational|programming", {"verify": False}),
    ]
    for url, kwargs in attempts:
        try:
            resp = requests.get(url, timeout=10, **kwargs)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    text = data[0].get('q', '')
                    author = data[0].get('a', 'Unknown')
                else:
                    text = data.get('content', '')
                    author = data.get('author', 'Unknown')
                if len(text) <= 40:
                    return text, author
                if len(text) < best_len:
                    best = (text, author)
                    best_len = len(text)
        except Exception:
            continue
    return best


# ============================================================
# GitHub GraphQL Queries
# ============================================================
def get_user_id():
    query = '''
    query($login: String!) {
        user(login: $login) {
            id
            createdAt
        }
    }'''
    data = graphql_request('user_getter', query, {'login': USER_NAME})
    return data['data']['user']['id'], data['data']['user']['createdAt']


def get_followers():
    query = '''
    query($login: String!) {
        user(login: $login) {
            followers { totalCount }
        }
    }'''
    data = graphql_request('follower_getter', query, {'login': USER_NAME})
    return data['data']['user']['followers']['totalCount']


def get_repos_and_stars():
    """Get total repos and stars for owned repositories"""
    query = '''
    query($login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: [OWNER]) {
                totalCount
                edges {
                    node {
                        nameWithOwner
                        stargazers { totalCount }
                    }
                }
                pageInfo { endCursor, hasNextPage }
            }
        }
    }'''
    total_repos = 0
    total_stars = 0
    cursor = None
    while True:
        data = graphql_request('graph_repos_stars', query, {'login': USER_NAME, 'cursor': cursor})
        repos = data['data']['user']['repositories']
        total_repos = repos['totalCount']
        for edge in repos['edges']:
            node = edge.get('node') or {}
            stars = (node.get('stargazers') or {}).get('totalCount') or 0
            total_stars += stars
        if not repos['pageInfo']['hasNextPage']:
            break
        cursor = repos['pageInfo']['endCursor']
    return total_repos, total_stars



def get_language_bytes():
    """Sum linguist bytes across owned non-fork repositories."""
    query = '''
    query($login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: [OWNER], isFork: false) {
                edges {
                    node {
                        languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
                            edges { size node { name } }
                        }
                    }
                }
                pageInfo { endCursor, hasNextPage }
            }
        }
    }'''
    totals = Counter()
    cursor = None
    while True:
        data = graphql_request('graph_languages', query, {'login': USER_NAME, 'cursor': cursor})
        repos = data['data']['user']['repositories']
        for edge in repos['edges']:
            node = edge.get('node') or {}
            langs = node.get('languages') or {}
            for lang in langs.get('edges') or []:
                lang_node = lang.get('node') or {}
                name = lang_node.get('name')
                if name:
                    totals[name] += lang.get('size') or 0
        if not repos['pageInfo']['hasNextPage']:
            break
        cursor = repos['pageInfo']['endCursor']
    return totals



def get_total_commits(start_date, end_date):
    query = '''
    query($login: String!, $start: DateTime!, $end: DateTime!) {
        user(login: $login) {
            contributionsCollection(from: $start, to: $end) {
                contributionCalendar { totalContributions }
            }
        }
    }'''
    data = graphql_request('graph_commits', query, {
        'login': USER_NAME,
        'start': start_date,
        'end': end_date
    })
    return data['data']['user']['contributionsCollection']['contributionCalendar']['totalContributions']


def compute_streaks(days, today):
    """days: [(YYYY-MM-DD, count), ...]. today: YYYY-MM-DD. Returns (current, longest)."""
    longest = run = 0
    for _, count in days:
        if count > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    upto = [(d, c) for d, c in days if d <= today]
    if upto and upto[-1][1] == 0:
        upto = upto[:-1]
    current = 0
    for _, count in reversed(upto):
        if count > 0:
            current += 1
        else:
            break
    return current, longest


assert compute_streaks([('2026-09-13', 1), ('2026-09-14', 1), ('2026-09-15', 1)], '2026-09-15') == (3, 3)
assert compute_streaks([('2026-09-14', 1), ('2026-09-15', 0)], '2026-09-15') == (1, 1)
assert compute_streaks([('2026-09-13', 1), ('2026-09-14', 0), ('2026-09-15', 1)], '2026-09-15') == (1, 1)


def contribution_days(from_iso, to_iso):
    query = '''
    query($login: String!, $from: DateTime!, $to: DateTime!) {
        user(login: $login) {
            contributionsCollection(from: $from, to: $to) {
                contributionCalendar {
                    weeks { contributionDays { date contributionCount } }
                }
            }
        }
    }'''
    data = graphql_request('graph_streak', query, {
        'login': USER_NAME,
        'from': from_iso,
        'to': to_iso,
    })
    weeks = data['data']['user']['contributionsCollection']['contributionCalendar']['weeks']
    return [
        (d['date'], d['contributionCount'])
        for week in weeks
        for d in week['contributionDays']
    ]


def get_streaks(created_at):
    """Current + all-time longest contribution streak (GitHub calendar, USER_TZ today)."""
    created = datetime.datetime.fromisoformat(created_at.replace('Z', '+00:00'))
    now = datetime.datetime.now(datetime.timezone.utc)
    days_map = {}
    start = created
    year = datetime.timedelta(days=365) - datetime.timedelta(seconds=1)
    while start < now:
        end = min(start + year, now)
        for date, count in contribution_days(start.isoformat(), end.isoformat()):
            days_map[date] = count
        start = end + datetime.timedelta(seconds=1)
    days = sorted(days_map.items())
    today = datetime.datetime.now(USER_TZ).date().isoformat()
    return compute_streaks(days, today)



def get_loc(owner_affiliation):
    """Compute total lines of code (additions - deletions) across repositories"""
    query = '''
    query($login: String!, $cursor: String, $affiliation: [RepositoryAffiliation]) {
        user(login: $login) {
            repositories(first: 60, after: $cursor, ownerAffiliations: $affiliation) {
                edges {
                    node {
                        nameWithOwner
                        defaultBranchRef {
                            target {
                                ... on Commit {
                                    history { totalCount }
                                }
                            }
                        }
                    }
                }
                pageInfo { endCursor, hasNextPage }
            }
        }
    }'''
    all_edges = []
    cursor = None
    while True:
        data = graphql_request('loc_query', query, {
            'login': USER_NAME, 'cursor': cursor, 'affiliation': owner_affiliation
        })
        repos = data['data']['user']['repositories']
        all_edges.extend(repos['edges'])
        if not repos['pageInfo']['hasNextPage']:
            break
        cursor = repos['pageInfo']['endCursor']

    # Cache file
    cache_dir = 'cache'
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, hashlib.sha256(USER_NAME.encode()).hexdigest() + '.txt')

    # Load existing cache
    cached = {}
    if os.path.exists(cache_file):
        with open(cache_file, 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 5:
                    cached[parts[0]] = {'commits': int(parts[1]), 'add': int(parts[3]), 'del': int(parts[4])}

    total_add = 0
    total_del = 0
    total_commits = 0

    for edge in all_edges:
        repo = edge['node']
        name = repo['nameWithOwner']
        repo_hash = hashlib.sha256(name.encode()).hexdigest()
        commit_count = repo['defaultBranchRef']['target']['history']['totalCount'] if repo['defaultBranchRef'] else 0

        cached_entry = cached.get(repo_hash)
        if cached_entry and cached_entry['commits'] == commit_count:
            total_add += cached_entry['add']
            total_del += cached_entry['del']
            total_commits += cached_entry['commits']
            continue

        # Fetch LOC for this repo
        add, delete, my_commits = fetch_repo_loc(name, commit_count)
        total_add += add
        total_del += delete
        total_commits += my_commits

        # Update cache
        cached[repo_hash] = {'commits': commit_count, 'add': add, 'del': delete}

    # Save cache
    with open(cache_file, 'w') as f:
        for h, v in cached.items():
            f.write(f"{h} {v['commits']} {v.get('my_commits', 0)} {v['add']} {v['del']}\n")

    return total_add, total_del, total_add - total_del, total_commits


def fetch_repo_loc(name_with_owner, total_commits):
    """Fetch LOC for a single repository by iterating through commit history"""
    owner, repo_name = name_with_owner.split('/')
    query = '''
    query($owner: String!, $repo: String!, $cursor: String) {
        repository(owner: $owner, name: $repo) {
            defaultBranchRef {
                target {
                    ... on Commit {
                        history(first: 100, after: $cursor) {
                            totalCount
                            edges {
                                node {
                                    author { user { id } }
                                    additions
                                    deletions
                                }
                            }
                            pageInfo { endCursor, hasNextPage }
                        }
                    }
                }
            }
        }
    }'''

    # Get user ID for filtering
    user_id = get_user_id()[0]

    total_add = 0
    total_del = 0
    my_commits = 0
    cursor = None

    while True:
        data = graphql_request('recursive_loc', query, {
            'owner': owner, 'repo': repo_name, 'cursor': cursor
        })
        history = data['data']['repository']['defaultBranchRef']['target']['history']
        for edge in history['edges']:
            node = edge['node']
            if node['author']['user'] and node['author']['user']['id'] == user_id:
                my_commits += 1
                total_add += node['additions']
                total_del += node['deletions']
        if not history['pageInfo']['hasNextPage']:
            break
        cursor = history['pageInfo']['endCursor']

    return total_add, total_del, my_commits


# ============================================================
# SVG Update
# ============================================================
def justify_format(root, element_id, new_text, length=0):
    if isinstance(new_text, int):
        new_text = f"{new_text:,}"
    new_text = str(new_text)

    elem = root.find(f".//*[@id='{element_id}']")
    if elem is None:
        return
    old = elem.text or ''
    elem.text = new_text

    # Grow/shrink existing leader dots by the char delta so full-width layout stays.
    dots_elem = root.find(f".//*[@id='{element_id}_dots']")
    if dots_elem is None or dots_elem.text is None:
        return
    delta = len(new_text) - len(old)
    if delta == 0:
        return
    inner = dots_elem.text
    lead = len(inner) - len(inner.lstrip(' '))
    trail = len(inner) - len(inner.rstrip(' '))
    core = inner.strip(' ')
    if not core or set(core) - {'.'}:
        return
    if delta > 0:
        core = core[delta:] if len(core) > delta else '.'
    else:
        core = core + ('.' * (-delta))
    dots_elem.text = (' ' * lead) + core + (' ' * trail)


def update_quote(root, quote_text, author_name):
    """Update quote text (short quotes only — no wrapping needed)."""
    text_el = root.find(".//*[@id='quote_text']")
    author_el = root.find(".//*[@id='quote_author']")
    if text_el is not None:
        text_el.text = quote_text
    if author_el is not None:
        author_el.text = f"~ {author_name}"


def update_svg(svg_path, stats, quote):
    tree = etree.parse(svg_path)
    root = tree.getroot()

    # Keep static Uptime text in the SVG (e.g. "4+ years").
    if 'repos' in stats:
        justify_format(root, 'repo_data', stats['repos'], 6)
    if 'stars' in stats:
        justify_format(root, 'star_data', stats['stars'], 14)
    justify_format(root, 'commit_data', stats['commits'], 22)
    justify_format(root, 'follower_data', stats['followers'], 10)
    justify_format(root, 'streak_data', stats['streak'])
    justify_format(root, 'longest_data', stats['longest'])
    if 'expertise' in stats:
        justify_format(root, 'expertise_data', stats['expertise'])
        justify_format(root, 'project_data', stats['project'])
        justify_format(root, 'programming_data', stats['programming'])
        justify_format(root, 'computer_data', stats['computer'])
        justify_format(root, 'loc_data', stats['programming'])

    if quote is not None:
        update_quote(root, quote[0], quote[1])

    tree.write(svg_path, encoding='utf-8', xml_declaration=True)
    print(f"Updated {svg_path}")



# ============================================================
# Main
# ============================================================
def main():
    print("=== GitHub Profile Updater ===")
    print(f"User: {USER_NAME}")

    quote = None
    if os.environ.get('UPDATE_QUOTE') == '1':
        print("Fetching quote...")
        quote = fetch_quote()
        print(f"Quote: \"{quote[0]}\" — {quote[1]}")


    print("Fetching GitHub stats...")
    user_id, created_at = get_user_id()

    acc_date = datetime.datetime.fromisoformat(created_at.replace('Z', '+00:00'))
    age = daily_readme(acc_date)

    end_date = datetime.datetime.now(datetime.timezone.utc).isoformat()
    start_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=365)).isoformat()
    commits = get_total_commits(start_date, end_date)

    followers = get_followers()
    streak, longest = get_streaks(created_at)

    stats = {
        'age': age,
        'commits': commits,
        'followers': followers,
        'streak': f"{streak} day{format_plural(streak)}",
        'longest': f"{longest} day{format_plural(longest)}",
    }

    if HAS_REPO_TOKEN:
        print("Fetching repository languages...")
        repos, stars = get_repos_and_stars()
        programming, computer = classify_languages(get_language_bytes())
        expertise = derive_expertise(programming)
        project = derive_project(programming)
        programming_text = ', '.join(programming) if programming else 'TypeScript, Swift'
        stats['repos'] = repos
        stats['stars'] = stars
        stats['expertise'] = ', '.join(expertise)
        stats['project'] = project
        stats['programming'] = programming_text
        stats['computer'] = ', '.join(computer)
    else:
        print("ACCESS_TOKEN unset; leaving repos/stars/languages unchanged")

    print(f"\nStats:")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    print("\nUpdating SVGs...")
    update_svg('assets/dark_mode.svg', stats, quote)
    update_svg('assets/light_mode.svg', stats, quote)

    print("\n=== Done ===")
    print(f"Total GraphQL queries: {sum(QUERY_COUNT.values())}")
    for k, v in QUERY_COUNT.items():
        if v:
            print(f"  {k}: {v}")



if __name__ == '__main__':
    if not GRAPHQL_TOKEN:
        print("ERROR: ACCESS_TOKEN or GITHUB_TOKEN required")
        sys.exit(1)
    main()

