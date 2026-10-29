#!/usr/bin/env python3
"""Builds a public branch of a specialist package from its working branch, so it can be rebuilt after every release.

The working branch (main) may hold things that must not go public: another language, private names, internal links.
The public branch is an orphan branch (none of the working history) whose tree is main's tree passed through a
translation memory:

- a unit is a Markdown/text block (split by blank lines), a line of code, or a JSON string;
- a unit that needs work (non-ASCII letters of the source language, a secret, a word from the deny list) is looked up
  in the memory by the hash of its text: the memory gives its public text, "" drops it (a JSON string: the whole list
  item it sits in, such as one tool of a manifest); a unit that needs no work passes as it is, unless the memory has an
  entry for it (`learn` takes `{"text": …, "public": …}` without a key: that is how a plain English tool id is dropped);
- files listed in "drop" are left out, files in "add" are added as they are;
- whole lines from one holding `release:private` to one holding `/release:private` (in any comment syntax:
  `<!-- release:private -->`, `# release:private`, `/* release:private */`) are cut before anything else: what only
  this hub's own agents should read (its clients, prices, campaigns) stays in main and never reaches the public branch,
  even if it is plain English.

The memory lives in the private branch `release/memory` (memory.json) and never goes public.

  public_branch.py todo  <repo> [--deny FILE] [--out todo.json]   units of main that the memory lacks
  public_branch.py learn <repo> todo.json                           put the filled "public" fields into the memory
  public_branch.py build <repo> [--deny FILE] [--source main]       commit main's tree, translated, to release/public

`build` refuses while anything is untranslated, or while the result still holds a leak. Nothing is pushed.
The deny file holds one regular expression per line (private names, internal domains); keep it outside the repo.
"""
import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

PUBLIC, MEMORY = "release/public", "release/memory"
SOURCE_LETTERS = re.compile(r"[Ѐ-ӿ]")        # the source language of the working branch
KEYS = re.compile(r"sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[abp]-[A-Za-z0-9-]{10,}|"
                  r"AKIA[0-9A-Z]{16}|Bearer\s+[A-Za-z0-9._-]{20,}|\b\d{8,10}:[A-Za-z0-9_-]{34,}|"
                  r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|-----BEGIN [A-Z ]*PRIVATE KEY-----")
LEAKS = [("key or token", KEYS),
         ("private block left (unclosed release:private)", re.compile(r"release:private")),
         ("personal path", re.compile(r"/Users/[A-Za-z]|/home/[a-z]|[A-Za-z]:\\Users\\", re.I)),
         ("task or message number", re.compile(r"\b[qmd]\d{3,}\b"))]
CODE = (".py", ".js", ".mjs", ".ts", ".css", ".html", ".sh", ".toml", ".yml", ".yaml")


def git(repo, *args, data=None):
    r = subprocess.run(["git", "-C", repo, *args], input=data, capture_output=True)
    if r.returncode:
        raise SystemExit(f"git {' '.join(args)}: {r.stderr.decode('utf-8', 'replace').strip()}")
    return r.stdout


def key(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def deny_list(path):
    if not path:
        return []
    with open(path, encoding="utf-8") as f:
        return [re.compile(line.strip(), re.I) for line in f if line.strip() and not line.startswith("#")]


def load_memory(repo):
    try:
        mem = json.loads(git(repo, "show", f"{MEMORY}:memory.json").decode("utf-8"))
    except SystemExit:
        mem = {}
    for k, v in (("units", {}), ("drop", []), ("add", {}), ("keep_source_language", [])):
        mem.setdefault(k, v)
    return mem


def save_memory(repo, mem, message):
    blob = git(repo, "hash-object", "-w", "--stdin",
               data=(json.dumps(mem, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")).decode().strip()
    tree = git(repo, "mktree", data=f"100644 blob {blob}\tmemory.json\n".encode()).decode().strip()
    commit(repo, MEMORY, tree, message)


def commit(repo, branch, tree, message):
    try:
        parent = git(repo, "rev-parse", "--verify", "-q", branch).decode().strip()
    except SystemExit:
        parent = ""
    if parent and git(repo, "rev-parse", parent + "^{tree}").decode().strip() == tree:
        return parent, False
    args = ["commit-tree", tree, "-m", message] + (["-p", parent] if parent else [])
    sha = git(repo, *args).decode().strip()
    git(repo, "update-ref", f"refs/heads/{branch}", sha)
    return sha, True


def needs_work(text, deny):
    return bool(SOURCE_LETTERS.search(text) or KEYS.search(text) or any(rx.search(text) for rx in deny))


def units_of(path, text):
    """(kind, unit text) pieces of a file; kind decides how pieces join back."""
    if path.endswith(".json"):
        return "json", None
    if path.endswith(CODE):
        return "lines", text.split("\n")
    return "blocks", re.split(r"(\n{2,})", text)


def json_strings(node, at=()):
    if isinstance(node, str):
        yield at, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from json_strings(v, at + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from json_strings(v, at + (i,))


def json_set(node, at, value):
    for step in at[:-1]:
        node = node[step]
    node[at[-1]] = value


def cut_private(text):
    """The text without its private blocks: whole lines from `release:private` to `/release:private`. An unclosed
    block is left in place, so the leak check stops the build."""
    out, depth = [], 0
    lines = text.split("\n")
    for n, line in enumerate(lines):
        closes, opens = "/release:private" in line, "release:private" in line.replace("/release:private", "")
        if opens and not depth and not any("/release:private" in x for x in lines[n:]):
            return text
        if opens:
            depth += 1
        if not depth:
            out.append(line)
        if closes and depth:
            depth -= 1
    return "\n".join(out)


def translate(path, text, mem, deny, missing):
    """Public text of one file; units the memory lacks go to `missing`. None: the file is dropped whole."""
    crlf = "\r\n" in text
    text = cut_private(text.replace("\r\n", "\n"))
    kind, parts = units_of(path, text)
    keep = any(fnmatch.fnmatch(path, g) for g in mem["keep_source_language"])
    if kind == "json":
        try:
            data = json.loads(text)
        except ValueError:
            kind, parts = "blocks", re.split(r"(\n{2,})", text)
        else:
            gone = []
            for at, s in list(json_strings(data)):
                if at[:1] == ("i18n",) or (keep and not KEYS.search(s)) or not (needs_work(s, deny) or key(s) in mem["units"]):
                    continue
                k = key(s)
                if k not in mem["units"]:
                    missing.append({"key": k, "file": path, "text": s, "public": None})
                elif mem["units"][k] == "" and any(isinstance(i, int) for i in at):
                    gone.append(at[:max(n for n, i in enumerate(at) if isinstance(i, int)) + 1])
                else:
                    json_set(data, at, mem["units"][k])
            for at in sorted(set(gone), reverse=True):    # the last index first, so the others stay valid
                node = data
                for step in at[:-1]:
                    node = node[step]
                del node[at[-1]]
            out = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
            return out.replace("\n", "\r\n") if crlf else out
    out = []
    for i, part in enumerate(parts):
        if kind == "blocks" and i % 2:                # the separators between blocks
            out.append(part)
            continue
        if not part.strip() or (keep and not KEYS.search(part)) or not (needs_work(part, deny) or key(part) in mem["units"]):
            out.append(part)
            continue
        k = key(part)
        if k in mem["units"]:
            out.append(mem["units"][k])
        else:
            missing.append({"key": k, "file": path, "text": part, "public": None})
            out.append(part)
    if kind == "lines":
        result = "\n".join(p for p, src in zip(out, parts) if not (p == "" and src.strip()))
    else:
        result = "".join(out)
        result = re.sub(r"\n{3,}", "\n\n", result)    # a dropped block leaves no hole
    return result.replace("\n", "\r\n") if crlf else result


def source_files(repo, source):
    rows = git(repo, "ls-tree", "-r", "-z", source).decode("utf-8").split("\0")
    for row in filter(None, rows):
        meta, path = row.split("\t", 1)
        mode, _type, sha = meta.split()
        yield path, mode, sha


def walk(repo, source, mem, deny):
    """(files {path: (mode, bytes)}, missing units) of the public tree."""
    files, missing = {}, []
    for path, mode, sha in source_files(repo, source):
        if any(fnmatch.fnmatch(path, g) for g in mem["drop"]):
            continue
        raw = git(repo, "cat-file", "blob", sha)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            files[path] = (mode, raw)                 # binary: as it is
            continue
        files[path] = (mode, translate(path, text, mem, deny, missing).encode("utf-8"))
    for path, text in mem["add"].items():
        files[path] = ("100644", text.encode("utf-8"))
    seen, unique = set(), []
    for m in missing:
        if m["key"] not in seen:
            seen.add(m["key"])
            unique.append(m)
    return files, unique


def leaks(files, mem, deny):
    found = []
    for path, (_mode, raw) in sorted(files.items()):
        text = raw.decode("utf-8", "replace")
        keep = any(fnmatch.fnmatch(path, g) for g in mem["keep_source_language"])
        checks = list(LEAKS) + [("denied word", rx) for rx in deny]
        if not keep:
            if path.endswith(".json"):
                try:
                    data = json.loads(text)
                    text = "\n".join(s for at, s in json_strings(data) if at[:1] != ("i18n",))
                except ValueError:
                    pass
            checks.append(("source language", SOURCE_LETTERS))
        for no, line in enumerate(text.splitlines(), 1):
            for kind, rx in checks:
                m = rx.search(line)
                if m:
                    shown = "(hidden)" if kind == "key or token" else m.group(0)
                    found.append(f"{path}:{no}: {kind} {shown!r}")
    return found


def write_tree(repo, files):
    """A nested tree object from {path: (mode, bytes)} without touching the working copy."""
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(tmp, "index"))
        lines = []
        for path, (mode, raw) in sorted(files.items()):
            blob = git(repo, "hash-object", "-w", "--stdin", data=raw).decode().strip()
            lines.append(f"{mode} {blob}\t{path}")
        r = subprocess.run(["git", "-C", repo, "update-index", "--add", "--index-info"], env=env,
                           input="\n".join(lines).encode("utf-8") + b"\n", capture_output=True)
        if r.returncode:
            raise SystemExit(r.stderr.decode("utf-8", "replace"))
        return subprocess.run(["git", "-C", repo, "write-tree"], env=env, capture_output=True,
                              check=True).stdout.decode().strip()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("todo", "build"):
        p = sub.add_parser(name)
        p.add_argument("repo")
        p.add_argument("--deny")
        p.add_argument("--source", default="main")
        if name == "todo":
            p.add_argument("--out", default="todo.json")
    p = sub.add_parser("learn")
    p.add_argument("repo")
    p.add_argument("todo")
    args = ap.parse_args(argv)
    mem = load_memory(args.repo)
    if args.cmd == "learn":
        with open(args.todo, encoding="utf-8") as f:
            items = json.load(f)
        if isinstance(items, dict):                   # {"units": [...], "drop": [...], "add": {...}, "keep_source_language": [...]}
            for k in ("drop", "keep_source_language"):
                mem[k] = sorted(set(mem[k]) | set(items.get(k, [])))
            mem["add"].update(items.get("add", {}))
            items = items.get("units", [])
        done = [i for i in items if isinstance(i.get("public"), str)]
        for i in done:
            mem["units"][i.get("key") or key(i["text"])] = i["public"]
        save_memory(args.repo, mem, f"Memory: {len(done)} units")
        print(f"learned {len(done)} of {len(items)} units")
        return
    deny = deny_list(args.deny)
    files, missing = walk(args.repo, args.source, mem, deny)
    if args.cmd == "todo":
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(missing, f, ensure_ascii=False, indent=1)
        print(f"{len(missing)} units to translate -> {args.out}")
        return
    if missing:
        raise SystemExit(f"{len(missing)} units untranslated: run todo, fill them, learn")
    bad = leaks(files, mem, deny)
    if bad:
        raise SystemExit("leaks in the public tree:\n  " + "\n  ".join(bad[:60]) + (f"\n  … {len(bad) - 60} more" if len(bad) > 60 else ""))
    src = git(args.repo, "rev-parse", "--short", args.source).decode().strip()
    sha, made = commit(args.repo, PUBLIC, write_tree(args.repo, files), f"Public build of {args.source} {src}")
    print(f"{PUBLIC} {'->' if made else 'unchanged at'} {sha[:12]} ({len(files)} files)")


if __name__ == "__main__":
    main()
