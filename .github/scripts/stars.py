"""
Total GitHub stars over time, across all of a user's repositories.

Reads the daily star counts of every public, non-fork repository the user owns (plus any
in EXTRA_REPOS) from GitHub's star history endpoint (GET /repos/{owner}/{repo}/stargazers/history,
which covers any public repository back to its creation and needs no special permission),
adds them up and draws the running total as two SVGs, one for GitHub's light theme and one
for its dark theme, plus a CSV of the same numbers.

Environment:
  GH_USER       GitHub user name (required)
  GITHUB_TOKEN  token for the GitHub API (the Actions token is enough)
  STARS_TOKEN   optional, a personal access token used instead of GITHUB_TOKEN
  EXTRA_REPOS   optional, comma-separated owner/repo to add (e.g. repos under an organisation)
  INCLUDE_FORKS optional, "1" to count forks too
  OUT_DIR       optional, default "stars"

Writes OUT_DIR/stars-light.svg, OUT_DIR/stars-dark.svg and OUT_DIR/stars.csv.
"""
import os
import re
import csv
import json
import logging
import datetime as dt
import urllib.error
import urllib.request

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)   # fonts named for the browser

API = "https://api.github.com"

THEMES = {   # series hue, text, muted text, gridline, axis; background stays transparent
    "light": dict(series="#2a78d6", text="#0b0b0b", secondary="#52514e", muted="#898781",
                  grid="#e1e0d9", axis="#c3c2b7"),
    "dark": dict(series="#3987e5", text="#f0efec", secondary="#c3c2b7", muted="#898781",
                 grid="#2c2c2a", axis="#383835"),
}


WARNED = set()


def get(url, accept="application/vnd.github+json", auth=True, version="2022-11-28"):
    """GET a GitHub API url, with STARS_TOKEN (or the workflow's token) if set. Public data is
    readable without a token too, so if the token is refused the request is repeated without it."""
    headers = {"Accept": accept, "X-GitHub-Api-Version": version, "User-Agent": "star-history"}
    token = os.environ.get("STARS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and auth:
        headers["Authorization"] = "Bearer " + token
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as r:
            return json.load(r), r.headers.get("Link", "")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode()).get("message", "")
        except Exception:
            msg = ""
        if token and auth and e.code in (401, 403, 404):
            if "token" not in WARNED:
                WARNED.add("token")
                print("note: the token was refused (%d %s); reading public data without it" % (e.code, msg))
            return get(url, accept, auth=False, version=version)
        if e.code == 403 and "rate limit" in msg.lower():
            msg += " (without a token only 60 requests per hour are allowed)"
        raise RuntimeError("GitHub API error %d on %s: %s" % (e.code, url, msg))


def pages(url, accept="application/vnd.github+json"):
    while url:
        data, link = get(url, accept)
        yield from data
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = m.group(1) if m else None


def history(full):
    """{date: stars given that day} for one repository, from the weekly star history
    (newest week first, up to 30 weeks per page, paging back to the creation week)"""
    days = {}
    for page in range(1, 101):
        data, _ = get("%s/repos/%s/stargazers/history?per_page=30&page=%d" % (API, full, page),
                      version="2026-03-10")
        for wk in data:
            start = dt.datetime.fromtimestamp(wk["week"], dt.timezone.utc).date()
            counts = wk.get("days") or []
            if not counts and wk.get("total"):
                counts = [wk["total"]]
            for i, n in enumerate(counts):
                if n:
                    d = start + dt.timedelta(days=i)
                    days[d] = days.get(d, 0) + n
        if len(data) < 30:
            break
    return days


def collect(user, extra=(), forks=False):
    """{owner/repo: {date: stars given that day}}"""
    try:
        listed = list(pages("%s/users/%s/repos?type=owner&per_page=100" % (API, user)))
    except RuntimeError as e:
        raise SystemExit(str(e))
    count = {r["full_name"]: r["stargazers_count"] for r in listed}
    repos = [r["full_name"] for r in listed
             if r["stargazers_count"] > 0 and (forks or not r["fork"]) and not r.get("private")]
    repos += [r for r in extra if r and r not in repos]
    out = {}
    for full in repos:
        try:
            days = history(full)
        except RuntimeError as e:
            if " 404 " in str(e):                     # gone or not visible at all: skip it, say so
                print("%-45s skipped (%s)" % (full, e))
                continue
            raise SystemExit(str(e))
        if days:
            out[full] = days
        n = sum(days.values())
        print("%-45s %5d stars%s" % (full, n, "" if full not in count or count[full] == n
                                      else "  (repository page says %d)" % count[full]))
    return out


def plot(by_repo, user, path, theme):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import MaxNLocator

    c = THEMES[theme]
    plt.rcParams.update({"svg.fonttype": "none", "font.size": 11,
                         "font.family": ["-apple-system", "Segoe UI", "Helvetica", "Arial", "DejaVu Sans"]})
    daily = {}
    for v in by_repo.values():
        for d, n in v.items():
            daily[d] = daily.get(d, 0) + n
    now = dt.datetime.now(dt.timezone.utc)
    dates = sorted(d for d in daily if d <= now.date())
    total = sum(daily[d] for d in dates)
    fig, ax = plt.subplots(figsize=(8, 3.4))
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")

    if dates:
        day = lambda d: dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc)
        cum, run = [], 0
        for d in dates:
            run += daily[d]
            cum.append(run)
        x = [day(dates[0])] + [day(d) for d in dates] + [now]
        y = [0] + cum + [total]
        ax.step(x, y, where="post", color=c["series"], lw=2, solid_joinstyle="round", solid_capstyle="round")
        ax.fill_between(x, y, step="post", color=c["series"], alpha=0.10, lw=0)
        ax.plot([now], [total], "o", ms=8, color=c["series"], clip_on=False, zorder=3)
        ax.annotate("%d" % total, (now, total), xytext=(10, 0), textcoords="offset points",
                    va="center", ha="left", color=c["text"], fontsize=13, fontweight="bold",
                    annotation_clip=False)
        ax.set_ylim(0, max(total * 1.12, 5))
        ax.set_xlim(day(dates[0]), now)
    else:
        ax.text(0.5, 0.5, "no stars yet", transform=ax.transAxes, ha="center", color=c["muted"])
        ax.set_axis_off()

    top = sorted(((k, sum(v.values())) for k, v in by_repo.items()), key=lambda kv: -kv[1])
    parts = ["%s %d" % (k.split("/", 1)[1], n) for k, n in top[:4]]
    if len(top) > 4:
        parts.append("%d in %d other repos" % (sum(n for _, n in top[4:]), len(top) - 4))
    fig.text(0.02, 0.97, "GitHub stars, all repositories", ha="left", va="top",
             color=c["text"], fontsize=13, fontweight="bold")
    fig.text(0.02, 0.885, " · ".join(parts), ha="left", va="top", color=c["secondary"], fontsize=10)

    ax.yaxis.set_major_locator(MaxNLocator(nbins=4, integer=True))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=7))
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
    ax.grid(axis="y", color=c["grid"], lw=1)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(c["axis"])
    ax.tick_params(colors=c["muted"], length=0, labelsize=10)
    ax.tick_params(axis="x", pad=6)
    fig.subplots_adjust(left=0.06, right=0.93, top=0.80, bottom=0.12)
    fig.savefig(path, transparent=True)
    plt.close(fig)


def main():
    user = os.environ["GH_USER"]
    extra = [r.strip() for r in os.environ.get("EXTRA_REPOS", "").split(",") if r.strip()]
    out = os.environ.get("OUT_DIR", "stars")
    os.makedirs(out, exist_ok=True)
    by_repo = collect(user, extra, os.environ.get("INCLUDE_FORKS") == "1")
    for theme in THEMES:
        plot(by_repo, user, os.path.join(out, "stars-%s.svg" % theme), theme)
    days = {}
    for v in by_repo.values():
        for d, n in v.items():
            days[d] = days.get(d, 0) + n
    with open(os.path.join(out, "stars.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "new_stars", "total_stars"])
        total = 0
        for d in sorted(days):
            total += days[d]
            w.writerow([d.isoformat(), days[d], total])
    print("total: %d stars across %d repos -> %s/" % (sum(sum(v.values()) for v in by_repo.values()), len(by_repo), out))


if __name__ == "__main__":
    main()
