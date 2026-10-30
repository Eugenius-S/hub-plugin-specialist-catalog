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
SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
DIFF_LINES = 40    # lines of the profile change the page shows; the rest is "and N more"


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


def listed_repo(package):
    """The catalog's address of a package ("" when the catalog does not list it)."""
    for item in read_json(CATALOG, []):
        if isinstance(item, dict) and item.get("name") == package and item.get("repo"):
            return item["repo"]
    return ""


def same_repo(a, b):
    """Two addresses of one repo (a trailing slash or .git aside)."""
    norm = lambda u: (u or "").strip().rstrip("/").removesuffix(".git").lower()
    return bool(a) and norm(a) == norm(b)


def catalog_repo(package, rec):
    """As `specialists update`: the address recorded at install wins, then the catalog's."""
    return rec.get("repo") or listed_repo(package)


def pin_for(package, rec):
    """The catalog's pin, only when the agent follows the catalog's own address ("" otherwise)."""
    return catalog_commit(package) if same_repo(catalog_repo(package, rec), listed_repo(package)) else ""


def catalog_commit(package):
    """The full sha the catalog pins the package to ("" = not pinned), as `specialists update` reads it."""
    for item in read_json(CATALOG, []):
        if isinstance(item, dict) and item.get("name") == package:
            c = str(item.get("commit") or "")
            return c if SHA.fullmatch(c) else ""
    return ""


def version_key(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v)))


def newer(latest, have):
    """True when latest is a later version than have; not comparable numbers — different strings count as newer."""
    if not latest or not have or latest == have:
        return False
    a, b = version_key(latest), version_key(have)
    return a > b if a and b else True


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=CLONE_WAIT, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})


def source(repo):
    """(address for git, plain): a local folder without .git is read as it is."""
    local = os.path.expanduser(repo)
    if os.path.isdir(local):
        return os.path.abspath(local), not os.path.isdir(os.path.join(local, ".git"))
    return repo, False


def fetch_commit(src, commit, to):
    """The commit by itself into `to` (shallow; a server that refuses a bare sha gets all branches). "" or the reason."""
    out = git("init", "-q", to)
    if out.returncode:
        return (out.stderr.strip().splitlines() or ["git init failed"])[-1][:200]
    for cmd in (("fetch", "-q", "--depth", "1", "--no-tags", "--", src, commit),
                ("fetch", "-q", "--no-tags", "--", src, "+refs/heads/*:refs/remotes/origin/*")):
        out = git("-C", to, *cmd)
        if not out.returncode and not git("-C", to, "cat-file", "-e", commit + "^{commit}").returncode:
            return ""
    return (out.stderr.strip().splitlines() or [f"the commit {commit[:12]} is not in the repo"])[-1][:200]


def latest_version(repo, commit=""):
    """(version, '') or ('', reason): the manifest's version in the pinned commit, else in the repo's last commit,
    without the package's other files."""
    src, plain = source(repo)
    if plain:
        return ("", "a pinned package must be a git repo") if commit else manifest_version(os.path.join(src, "hub-plugin.json"))
    tmp = tempfile.mkdtemp(prefix="specialists-check-")
    try:
        if commit:
            why = fetch_commit(src, commit, tmp + "/r")
            if why:
                return "", why
            ref = commit
        else:
            out = git("clone", "-q", "--depth", "1", "--filter=blob:none", "--no-checkout", "--", src, tmp + "/r")
            if out.returncode:
                return "", (out.stderr.strip().splitlines() or ["git clone failed"])[-1][:200]
            ref = "HEAD"
        show = git("-C", tmp + "/r", "show", f"{ref}:hub-plugin.json")
        if show.returncode:
            return "", "no hub-plugin.json in the package"
        return manifest_version(None, show.stdout)
    except (OSError, subprocess.SubprocessError) as e:
        return "", str(e)[:200] or e.__class__.__name__
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def plugin_names(text):
    """Names of the package's own plugins in its .claude-plugin/marketplace.json, as the CLI reads them."""
    try:
        market = json.loads(text)
    except (ValueError, TypeError):
        return []
    return [p["name"] for p in (market.get("plugins") if isinstance(market, dict) else None) or []
            if isinstance(p, dict) and isinstance(p.get("name"), str) and isinstance(p.get("source"), str)]


def tool_names(text):
    try:
        tools = json.loads(text)["agent"]["tools"]
        return [t["id"] for k in ("need", "optional") for t in tools[k] if isinstance(t, dict) and t.get("id")]
    except (ValueError, TypeError, KeyError):
        return []


def changes_of(repo, commit, rec):
    """What `specialists update` changes in the profile: CLAUDE.md lines, tools, plugins; None when it cannot be told.
    The installed commit is the base; a record without one has no profile diff, only the new side."""
    src, plain = source(repo)
    if plain or not commit:
        return None
    base = rec.get("commit") or ""
    tmp = tempfile.mkdtemp(prefix="specialists-diff-")
    try:
        if fetch_commit(src, commit, tmp + "/r"):
            return None
        at = lambda ref, path: (lambda o: o.stdout if not o.returncode else "")(git("-C", tmp + "/r", "show", f"{ref}:{path}"))
        tools = tool_names(at(commit, "hub-plugin.json"))
        plugins = plugin_names(at(commit, ".claude-plugin/marketplace.json"))
        out = {"base": base, "to": commit,
               "tools": {"added": [t for t in tools if t not in (rec.get("tool_ids") or [])],
                         "removed": [t for t in (rec.get("tool_ids") or []) if t not in tools]},
               "plugins": {"added": [p for p in plugins if p not in (rec.get("plugins") or [])],
                           "removed": [p for p in (rec.get("plugins") or []) if p not in plugins]}}
        have = bool(base) and not git("-C", tmp + "/r", "fetch", "-q", "--depth", "1", "--no-tags", "--", src, base).returncode
        if have:
            d = git("-C", tmp + "/r", "diff", "--no-color", "--unified=0", base, commit, "--", "CLAUDE.md").stdout
            lines = [l[:200] for l in d.splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---"))]
            out["profile"] = {"known": True, "added": sum(l[0] == "+" for l in lines),
                              "removed": sum(l[0] == "-" for l in lines), "lines": lines[:DIFF_LINES],
                              "more": max(0, len(lines) - DIFF_LINES)}
        else:
            out["profile"] = {"known": False, "added": len(at(commit, "CLAUDE.md").splitlines()), "removed": 0,
                              "lines": [], "more": 0}
        return out
    except (OSError, subprocess.SubprocessError):
        return None
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


def check_all(now=None, probe=latest_version, diff=changes_of):
    """Ask every installed package once (in parallel); the answers go to latest.json. A package the catalog pins to a
    commit is asked at that commit, and every agent behind it gets the preview of what its update changes."""
    packages = {}
    for rec in installed().values():
        packages.setdefault(rec.get("package") or "", rec)
    packages.pop("", None)
    got, seen = {}, {}

    def one(package, rec):
        version, err = probe(catalog_repo(package, rec), pin_for(package, rec))
        got[package] = {"version": version, "error": err}

    def preview(agent, rec):
        pin = pin_for(rec.get("package") or "", rec)
        if pin and rec.get("commit") and rec["commit"] != pin:
            seen[agent] = diff(catalog_repo(rec["package"], rec), pin, rec)

    threads = [threading.Thread(target=one, args=(p, r), daemon=True) for p, r in packages.items()]
    threads += [threading.Thread(target=preview, args=(a, r), daemon=True) for a, r in installed().items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join(CLONE_WAIT * 2 + 10)
    for package in packages:
        got.setdefault(package, {"version": "", "error": "timeout"})
    write_json(state_file("latest.json"), {"at": now or time.time(), "packages": got,
                                           "changes": {a: c for a, c in seen.items() if c}})


def build(req=""):
    """status.json: the installed versions now + the last answers about the latest ones."""
    seen = read_json(state_file("latest.json"), {})
    answers = seen.get("packages") or {}
    rows = {}
    for agent, rec in installed().items():
        a = answers.get(rec.get("package") or "") or {}
        latest = a.get("version") or ""
        pin = pin_for(rec.get("package") or "", rec)
        moved = bool(pin and rec.get("commit") and rec["commit"] != pin)   # same version, another commit: still an update
        ch = (seen.get("changes") or {}).get(agent)
        rows[agent] = {"package": rec.get("package") or agent, "installed": rec["version"], "latest": latest,
                       "update": newer(latest, rec["version"]) or (moved and not a.get("error")),
                       "error": a.get("error") or ""}
        if isinstance(ch, dict) and ch.get("base") == rec.get("commit") and ch.get("to") == pin:   # not a stale preview
            rows[agent]["changes"] = ch
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
