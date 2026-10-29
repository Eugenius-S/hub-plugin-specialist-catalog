#!/usr/bin/env python3
"""Specialists catalog, plugin process: "Check for updates" on the page.

The page posts "check <token>" to the plugin channel (hub.postFeed). The process asks every installed package for its
latest version (a shallow clone of its repo: the same repo and the same git access that `specialists update` uses),
and writes status.json next to this file: per agent the installed version, the latest one, update true/false. The page
reads status.json (no-cache) and shows "Update" where a newer version is out. The installed versions come from
<state>/specialists/state.json and are re-read every few seconds, so after `specialists update` the row clears by itself.
Only reads: it never installs or updates anything (that is the hub's, on the owner's request)."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.expanduser(os.environ.get("HUB_STATE_DIR") or os.environ.get("HUB_STATE") or "~/.hub-core")
CHANNEL = os.environ.get("HUB_EXTENSION", "specialists").split(":")[-1] or "specialists"
CATALOG = os.environ.get("SPECIALISTS_CATALOG") or os.path.join(HERE, "specialists.json")
STATUS = os.environ.get("SPECIALISTS_STATUS") or os.path.join(HERE, "status.json")
EVERY = 2          # s: how often the channel and state.json are looked at
CLONE_WAIT = 90    # s: one package; a slower repo is a reason, not a hang
TOKEN = re.compile(r"check\s+([A-Za-z0-9._-]{1,64})")


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)


def state_file(name):
    return os.path.join(STATE, "specialists", name)


def installed():
    """{agent: {package, version, repo}} from the CLI's state.json."""
    got = read_json(state_file("state.json"), {}).get("installed")
    return {a: v for a, v in (got or {}).items() if isinstance(v, dict) and v.get("version")}


def catalog_repo(package, rec):
    """As `specialists update`: the catalog's address wins, then the one recorded at install."""
    for item in read_json(CATALOG, []):
        if isinstance(item, dict) and item.get("name") == package and item.get("repo"):
            return item["repo"]
    return rec.get("repo") or ""


def version_key(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v)))


def newer(latest, have):
    """True when latest is a later version than have; not comparable numbers — different strings count as newer."""
    if not latest or not have or latest == have:
        return False
    a, b = version_key(latest), version_key(have)
    return a > b if a and b else True


def latest_version(repo):
    """(version, '') or ('', reason): the manifest's version in the repo's last commit, without the package's files."""
    local = os.path.expanduser(repo)
    if os.path.isdir(local) and not os.path.isdir(os.path.join(local, ".git")):
        return manifest_version(os.path.join(local, "hub-plugin.json"))
    tmp = tempfile.mkdtemp(prefix="specialists-check-")
    try:
        src = os.path.abspath(local) if os.path.isdir(local) else repo
        out = subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--no-checkout", src, tmp + "/r"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=CLONE_WAIT,
                             env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        if out.returncode:
            return "", (out.stderr.strip().splitlines() or ["git clone failed"])[-1][:200]
        show = subprocess.run(["git", "-C", tmp + "/r", "show", "HEAD:hub-plugin.json"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=CLONE_WAIT)
        if show.returncode:
            return "", "no hub-plugin.json in the package"
        return manifest_version(None, show.stdout)
    except (OSError, subprocess.SubprocessError) as e:
        return "", str(e)[:200] or e.__class__.__name__
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def manifest_version(path, text=None):
    try:
        if text is None:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        v = str(json.loads(text).get("version") or "").strip()
    except (OSError, ValueError, AttributeError):
        return "", "hub-plugin.json is not readable"
    return (v, "") if v else ("", "no version in hub-plugin.json")


def check_all(now=None, probe=latest_version):
    """Ask every installed package once (in parallel); the answers go to latest.json."""
    packages = {}
    for rec in installed().values():
        packages.setdefault(rec.get("package") or "", rec)
    packages.pop("", None)
    got = {}

    def one(package, rec):
        version, err = probe(catalog_repo(package, rec))
        got[package] = {"version": version, "error": err}

    threads = [threading.Thread(target=one, args=(p, r), daemon=True) for p, r in packages.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join(CLONE_WAIT * 2 + 10)
    for package in packages:
        got.setdefault(package, {"version": "", "error": "timeout"})
    write_json(state_file("latest.json"), {"at": now or time.time(), "packages": got})


def build(req=""):
    """status.json: the installed versions now + the last answers about the latest ones."""
    seen = read_json(state_file("latest.json"), {})
    answers = seen.get("packages") or {}
    rows = {}
    for agent, rec in installed().items():
        a = answers.get(rec.get("package") or "") or {}
        latest = a.get("version") or ""
        rows[agent] = {"package": rec.get("package") or agent, "installed": rec["version"], "latest": latest,
                       "update": newer(latest, rec["version"]), "error": a.get("error") or ""}
    return {"checked_at": seen.get("at") or 0, "req": req, "rows": rows}


def publish(req):
    status = build(req)
    if read_json(STATUS, None) != status:
        write_json(STATUS, status)
    return status


def hub_get(path):
    port = os.environ.get("HUB_WEB_PORT", "")
    url = f"http://127.0.0.1:{int(port) if port.isdigit() else 8787}{path}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # to itself: not through the proxy
    with opener.open(url, timeout=10) as r:
        return json.loads(r.read() or b"{}")


def posts(since):
    return hub_get(f"/api/feed?plugin={CHANNEL}&since={since}").get("posts") or []


def seq(post):
    m = re.fullmatch(r"p(\d+)", str(post.get("id") or ""))
    return int(m.group(1)) if m else 0


def requests(batch):
    """Tokens of the owner's "check <token>" posts in a batch of feed posts."""
    out = []
    for p in batch:
        m = TOKEN.fullmatch(str(p.get("text") or "").strip())
        if m and p.get("by") == "owner":
            out.append(m.group(1))
    return out


def loop():
    req = (read_json(STATUS, {}) or {}).get("req") or ""
    publish(req)
    try:   # old requests are not repeated after a restart
        since = max([seq(p) for p in posts(0)] or [0])
    except (OSError, ValueError):
        since = 0
    while True:
        time.sleep(EVERY)
        try:
            batch = posts(since)
        except (OSError, ValueError):
            batch = []   # the hub is restarting: look again
        since = max([since] + [seq(p) for p in batch])
        tokens = requests(batch)
        if tokens:
            try:
                check_all()
            except Exception as e:   # noqa: BLE001 - a failed check is a reason on the page, not a dead process
                write_json(state_file("latest.json"), {"at": time.time(), "packages": {
                    p.get("package") or a: {"version": "", "error": str(e)[:200]} for a, p in installed().items()}})
            req = tokens[-1]
        publish(req)


if __name__ == "__main__":
    sys.exit(loop() if "--once" not in sys.argv[1:] else (check_all(), publish(""), 0)[-1])
