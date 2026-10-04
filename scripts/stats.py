"""Сбор статистики репозитория через gh CLI (нужны права владельца).

python scripts/stats.py [owner/repo] [history.json]
"""
import json, subprocess, sys
from datetime import datetime, timezone

repo = sys.argv[1] if len(sys.argv) > 1 else "foridorpo-blip/netpulse"
hist_path = sys.argv[2] if len(sys.argv) > 2 else "netpulse_stats_history.json"

def api(path):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout else None

info = api(f"repos/{repo}") or {}
views = api(f"repos/{repo}/traffic/views") or {}
clones = api(f"repos/{repo}/traffic/clones") or {}
refs = api(f"repos/{repo}/traffic/popular/referrers") or []
paths = api(f"repos/{repo}/traffic/popular/paths") or []
releases = api(f"repos/{repo}/releases") or []

assets = {}
for rel in releases:
    for a in rel.get("assets", []):
        assets[f"{rel['tag_name']}/{a['name']}"] = a["download_count"]

snap = {
    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    "stars": info.get("stargazers_count"), "forks": info.get("forks_count"),
    "watchers": info.get("subscribers_count"), "open_issues": info.get("open_issues_count"),
    "release_downloads_total": sum(assets.values()), "release_downloads": assets,
    "views_14d": views.get("count"), "unique_visitors_14d": views.get("uniques"),
    "clones_14d": clones.get("count"), "unique_cloners_14d": clones.get("uniques"),
    "views_daily": {v["timestamp"][:10]: [v["count"], v["uniques"]] for v in views.get("views", [])},
    "clones_daily": {v["timestamp"][:10]: [v["count"], v["uniques"]] for v in clones.get("clones", [])},
    "referrers": [[r["referrer"], r["count"], r["uniques"]] for r in refs],
    "top_paths": [[p["path"], p["count"]] for p in paths[:5]],
}

try:
    hist = json.load(open(hist_path))
except Exception:
    hist = {"snapshots": [], "views_daily": {}, "clones_daily": {}}
prev = hist["snapshots"][-1] if hist["snapshots"] else None
hist["views_daily"].update(snap["views_daily"])   # GitHub хранит трафик только 14 дней
hist["clones_daily"].update(snap["clones_daily"])
hist["snapshots"] = [s for s in hist["snapshots"] if s["date"] != snap["date"]] + [
    {k: v for k, v in snap.items() if k not in ("views_daily", "clones_daily")}]
json.dump(hist, open(hist_path, "w"), ensure_ascii=False, indent=1)

snap["all_time_views"] = sum(v[0] for v in hist["views_daily"].values())
snap["all_time_clones"] = sum(v[0] for v in hist["clones_daily"].values())
snap["previous"] = prev
print(json.dumps(snap, ensure_ascii=False, indent=1))
