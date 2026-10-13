"""
Total GitHub stars over time, across all of a user's repositories.

Reads the date of every star of every public, non-fork repository the user owns (plus
any in EXTRA_REPOS), adds them up and draws the running total as two SVGs, one for
GitHub's light theme and one for its dark theme, plus a CSV of the same numbers.

Environment:
  GH_USER       GitHub user name (required)
  GITHUB_TOKEN  token for the GitHub API (the Actions token is enough)
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
import urllib.request

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)   # fonts named for the browser

API = "https://api.github.com"

THEMES = {   # series hue, text, muted text, gridline, axis; background stays transparent
    "light": dict(series="#2a78d6", text="#0b0b0b", secondary="#52514e", muted="#898781",
                  grid="#e1e0d9", axis="#c3c2b7"),
    "dark": dict(series="#3987e5", text="#f0efec", secondary="#c3c2b7", muted="#898781",
                 grid="#2c2c2a", axis="#383835"),
}


def get(url, accept="application/vnd.github+json"):
    headers = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "star-history"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as r:
        return json.load(r), r.headers.get("Link", "")


def pages(url, accept="application/vnd.github+json"):
    while url:
        data, link = get(url, accept)
        yield from data
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = m.group(1) if m else None


def collect(user, extra=(), forks=False):
    """{owner/repo: [star datetimes]}"""
    repos = [r["full_name"] for r in pages("%s/users/%s/repos?type=owner&per_page=100" % (API, user))
             if r["stargazers_count"] > 0 and (forks or not r["fork"])]
    repos += [r for r in extra if r and r not in repos]
    out = {}
    for full in repos:
        stars = [dt.datetime.fromisoformat(s["starred_at"].replace("Z", "+00:00"))
                 for s in pages("%s/repos/%s/stargazers?per_page=100" % (API, full),
                                "application/vnd.github.star+json")]
        if stars:
            out[full] = sorted(stars)
        print("%-45s %5d stars" % (full, len(stars)))
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
    times = sorted(t for v in by_repo.values() for t in v)
    now = dt.datetime.now(dt.timezone.utc)
    fig, ax = plt.subplots(figsize=(8, 3.4))
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")

    if times:
        x = [times[0]] + times + [now]
        y = [0] + list(range(1, len(times) + 1)) + [len(times)]
        ax.step(x, y, where="post", color=c["series"], lw=2, solid_joinstyle="round", solid_capstyle="round")
        ax.fill_between(x, y, step="post", color=c["series"], alpha=0.10, lw=0)
        ax.plot([now], [len(times)], "o", ms=8, color=c["series"], clip_on=False, zorder=3)
        ax.annotate("%d" % len(times), (now, len(times)), xytext=(10, 0), textcoords="offset points",
                    va="center", ha="left", color=c["text"], fontsize=13, fontweight="bold",
                    annotation_clip=False)
        ax.set_ylim(0, max(len(times) * 1.12, 5))
        ax.set_xlim(times[0], now)
    else:
        ax.text(0.5, 0.5, "no stars yet", transform=ax.transAxes, ha="center", color=c["muted"])
        ax.set_axis_off()

    top = sorted(by_repo.items(), key=lambda kv: -len(kv[1]))
    parts = ["%s %d" % (k.split("/", 1)[1], len(v)) for k, v in top[:4]]
    if len(top) > 4:
        parts.append("%d in %d other repos" % (sum(len(v) for _, v in top[4:]), len(top) - 4))
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
    for t in sorted(t for v in by_repo.values() for t in v):
        days[t.date().isoformat()] = days.get(t.date().isoformat(), 0) + 1
    with open(os.path.join(out, "stars.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "new_stars", "total_stars"])
        total = 0
        for d in sorted(days):
            total += days[d]
            w.writerow([d, days[d], total])
    print("total: %d stars across %d repos -> %s/" % (sum(len(v) for v in by_repo.values()), len(by_repo), out))


if __name__ == "__main__":
    main()
