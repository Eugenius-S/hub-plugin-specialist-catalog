"""Specialists catalog: package check, install, verify, update, remove. The hub is a fake; state lives in a temp folder."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins", "specialists", "bin", "specialists")
loader = importlib.machinery.SourceFileLoader("specialists_cli", BIN)
sp = importlib.util.module_from_spec(importlib.util.spec_from_loader("specialists_cli", loader))
loader.exec_module(sp)

MAN = {"name": "analyst", "kind": "specialist", "version": "0.1.0", "hub": "^1", "icon": "📊", "description": "Analyst",
       "why": "A ready-made analyst", "agent": {"cwd": "~/analyst", "cases": "evals/cases.md", "tools": {
           "need": [], "optional": [{"id": "research", "why": "ads"}, {"id": "web-search", "why": "search"},
                                    {"id": "nope", "why": "not in the hub"}]}}}
CLAUDE = "# analyst\nAgent file: `{AGENT_FILE}`\nFolder `{CWD}`\n"


def package(root, man=None, claude=CLAUDE, extra=None):
    os.makedirs(os.path.join(root, "evals"), exist_ok=True)
    with open(os.path.join(root, "hub-plugin.json"), "w", encoding="utf-8") as f:
        json.dump(MAN if man is None else man, f, ensure_ascii=False)
    with open(os.path.join(root, "evals", "cases.md"), "w", encoding="utf-8") as f:
        f.write("case 1\n")
    if claude is not None:
        with open(os.path.join(root, "CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write(claude)
    for name, text in (extra or {}).items():
        os.makedirs(os.path.dirname(os.path.join(root, name)), exist_ok=True)
        with open(os.path.join(root, name), "w", encoding="utf-8") as f:
            f.write(text)
    return root


def commit(root, message="pkg"):
    git = lambda *a: subprocess.run(["git", "-C", root, *a], check=True, capture_output=True)   # noqa: E731
    if not os.path.isdir(os.path.join(root, ".git")):
        git("init", "-q")
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message)


class FakeHub:
    """hub: status --json, version, tools list, session new/reload/close/remove, tools grant, send; records every call.
    obey: an agent asked to take its profile copies it into its agent file, like a real agent would."""
    def __init__(self, state):
        self.state, self.sessions, self.calls = state, {}, []
        self.close_to, self.remove_refused, self.obey = "asleep", False, True

    def agent_file(self, agent):
        return os.path.join(self.state, "agents", "sid-" + agent, "CLAUDE.md")

    def __call__(self, *args):
        self.calls.append(args)
        if args[:2] == ("status", "--json"):
            return 0, json.dumps({"sessions": self.sessions})
        if args[:1] == ("version",):
            return 0, "hub from source: v1.1.3 · abc"
        if args[:2] == ("tools", "list"):
            return 0, "  research    mcp  Ads  risk: external\n  web-search@my-skills plugin Search\n"
        if args[:2] == ("session", "new"):
            self.sessions[args[2]] = {"state": "idle", "session_id": "sid-" + args[2], "kind": "work",
                                      "role": "agent" if "--agent" in args else None}
            return 0, f"accepted: session.requested {args[2]} (#1)"
        if args[:2] == ("session", "close") and args[2] in self.sessions:
            self.sessions[args[2]]["state"] = self.close_to
            return 0, f"accepted: session.close_requested {args[2]} (#2)"
        if args[:2] == ("session", "remove") and args[2] in self.sessions:
            if self.remove_refused:
                return 1, "rejected: the hub or the owner does this, ask the hub"
            self.sessions[args[2]]["state"] = "removed"
            return 0, f"accepted: session.remove_requested {args[2]} (#3)"
        if args[:1] == ("send",) and self.obey and args[1] in self.sessions:
            m = re.search(r"with the content of (.+?), exactly", args[2])
            if m:
                os.makedirs(os.path.dirname(self.agent_file(args[1])), exist_ok=True)
                shutil.copyfile(m.group(1), self.agent_file(args[1]))
        return 0, "ok"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = os.path.join(self.tmp, "state")
        self.saved = {k: os.environ.get(k) for k in ("HUB_STATE_DIR", "HUB_CONFIG", "HUB_SESSION")}
        os.environ["HUB_STATE_DIR"] = self.state          # always: the live hub is never touched
        os.environ["HUB_CONFIG"] = os.path.join(self.tmp, "hub.json")
        os.environ.pop("HUB_SESSION", None)
        self.addCleanup(self.restore)
        self.pkg = package(os.path.join(self.tmp, "pkg"))
        self.hub = FakeHub(self.state)
        self.old = (sp.hub_run, sp.WAIT, sp.PROFILE_WAIT, sp.CATALOG)
        sp.hub_run, sp.WAIT, sp.PROFILE_WAIT = self.hub, 2, 2
        sp.CATALOG = os.path.join(self.tmp, "specialists.json")
        with open(sp.CATALOG, "w", encoding="utf-8") as f:
            json.dump([{"name": "analyst", "repo": self.pkg, "version": "0.1.0"}], f)
        self.addCleanup(self.unpatch)

    def restore(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def unpatch(self):
        sp.hub_run, sp.WAIT, sp.PROFILE_WAIT, sp.CATALOG = self.old

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            sp.main(list(argv))
        return out.getvalue()

    def fails(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as e:
            sp.main(list(argv))
        return str(e.exception)

    def install(self, *extra):
        return self.run_cli("install", "analyst", "--cwd", os.path.join(self.tmp, "work"), *extra)

    def state_file(self):
        with open(os.path.join(self.state, "specialists", "state.json"), encoding="utf-8") as f:
            return json.load(f)

    def sends(self, to=None):
        return [c for c in self.hub.calls if c[:1] == ("send",) and (to is None or c[1] == to)]

    def written_outside_own_folder(self):
        """Files the plugin wrote in the state folder outside <state>/specialists (the fake agent's own file excluded)."""
        found = []
        for dirpath, _dirs, files in os.walk(self.state):
            for f in files:
                rel = os.path.relpath(os.path.join(dirpath, f), self.state)
                if not rel.startswith("specialists") and not rel.startswith("agents"):
                    found.append(rel)
        return found


class Check(Base):
    def test_good_package_passes(self):
        man, bad = sp.check(self.pkg, 1)
        self.assertEqual((man["name"], bad), ("analyst", []))

    def test_missing_fields_are_named(self):
        broken = {k: v for k, v in MAN.items() if k not in ("why", "icon", "agent")}
        pkg = package(os.path.join(self.tmp, "p2"), man={**broken, "kind": "plugin"}, claude=None)
        bad = "\n".join(sp.check(pkg, 1)[1])
        for word in ("specialist", "why", "icon", "agent", "CLAUDE.md"):
            self.assertIn(word, bad)

    def test_agent_block_details(self):
        man = {**MAN, "agent": {"cwd": "", "cases": "evals/none.md", "tools": {"need": []}}}
        bad = "\n".join(sp.check(package(os.path.join(self.tmp, "p3"), man=man), 1)[1])
        for word in ("agent.cwd", "evals/none.md", "agent.tools"):
            self.assertIn(word, bad)

    def test_hub_version_must_fit(self):
        bad = sp.check(package(os.path.join(self.tmp, "p4"), man={**MAN, "hub": "^2"}), 1)[1]
        self.assertTrue(any("does not fit" in b for b in bad), bad)
        self.assertEqual(sp.check(package(os.path.join(self.tmp, "p5"), man={**MAN, "hub": "^1.15"}), 1)[1], [])

    def test_leaks_are_caught(self):
        extra = {"notes/a.md": "see /Users/someone/x\n", "notes/b.md": "on OneDrive\n", "notes/c.md": "as in m12345\n",
                 "notes/d.md": "token: abcdefghijklmnopqrstuvwxyz\n"}
        bad = "\n".join(sp.check(package(os.path.join(self.tmp, "p6"), extra=extra), 1)[1])
        for word in ("personal path", "cloud drive", "task or message number", "key or token"):
            self.assertIn(word, bad)

    def test_bad_manifest(self):
        root = os.path.join(self.tmp, "p7")
        os.makedirs(root)
        self.assertEqual(sp.check(root, 1)[1], ["no hub-plugin.json"])
        with open(os.path.join(root, "hub-plugin.json"), "w", encoding="utf-8") as f:
            f.write("[]")
        self.assertEqual(sp.check(root, 1)[1], ["hub-plugin.json is not a JSON object"])

    def test_rejected_package_installs_nothing(self):
        package(self.pkg, man={**MAN, "kind": "plugin"})
        self.assertIn("rejected", self.fails("install", "analyst"))
        self.assertFalse([c for c in self.hub.calls if c[:2] == ("session", "new")])


class Install(Base):
    def test_agent_gets_its_profile_and_is_verified(self):
        out = self.install()
        self.assertIn("Installed: analyst (analyst 0.1.0)", out)
        self.assertIn("matches the package profile", out)
        rec = self.state_file()["installed"]["analyst"]
        self.assertEqual(rec["profile"], "ok")
        self.assertEqual(rec["agent_file"], self.hub.agent_file("analyst"))
        text = pathlib.Path(rec["agent_file"]).read_text(encoding="utf-8")
        self.assertIn(rec["agent_file"], text)                         # placeholders filled
        self.assertIn(os.path.join(self.tmp, "work"), text)
        self.assertIn(("session", "reload", "analyst"), self.hub.calls)
        new = next(c for c in self.hub.calls if c[:2] == ("session", "new"))
        self.assertIn("--agent", new)

    def test_plugin_writes_only_its_own_folder(self):
        self.install()
        self.assertEqual(self.written_outside_own_folder(), [])
        self.assertFalse(os.path.exists(os.environ["HUB_CONFIG"]))     # hub.json untouched

    def test_agent_did_not_write_its_file(self):
        self.hub.obey = False
        out = self.install()
        self.assertIn("NOT READY", out)
        self.assertIn("profile pending: specialists verify analyst", out)
        self.assertEqual(self.state_file()["installed"]["analyst"]["profile"], "pending")
        self.assertNotIn(("session", "reload", "analyst"), self.hub.calls)

    def test_no_notify_prints_instead_of_sending(self):
        out = self.install("--no-notify")
        self.assertIn("[message to analyst, not sent]", out)
        self.assertEqual(self.sends(), [])
        self.assertEqual(self.state_file()["installed"]["analyst"]["profile"], "pending")

    def test_tools_are_asked_and_missing_named(self):
        out = self.install()
        grants = [c for c in self.hub.calls if c[:2] == ("tools", "grant")]
        self.assertEqual(grants, [("tools", "grant", "analyst", "research"),
                                  ("tools", "grant", "analyst", "web-search@my-skills")])
        self.assertIn("(risky: waits for the owner's yes)", out)
        self.assertIn("Not in this hub's catalog", out)
        self.assertEqual(self.state_file()["installed"]["analyst"]["tools"]["missing"], ["nope"])

    def test_tools_none(self):
        self.install("--tools", "none")
        self.assertFalse([c for c in self.hub.calls if c[:2] == ("tools", "grant")])

    def test_name_taken(self):
        self.install()
        self.assertIn("is taken", self.fails("install", "analyst"))
        self.hub.sessions["writer"] = {"state": "idle", "session_id": "sid-writer"}
        self.assertIn("--name <other>", self.fails("install", "analyst", "--name", "writer"))

    def test_other_name(self):
        out = self.install("--name", "analyst-2")
        self.assertIn("Installed: analyst-2", out)
        self.assertIn("analyst-2", self.state_file()["installed"])

    def test_only_hub_or_owner(self):
        self.hub.sessions["worker"] = {"state": "busy", "session_id": "sid-w", "kind": "work"}
        os.environ["HUB_SESSION"] = "worker"
        self.assertIn("only the hub or the owner", self.fails("install", "analyst"))
        self.hub.sessions["hub"] = {"state": "idle", "session_id": "sid-h", "kind": "hub"}
        os.environ["HUB_SESSION"] = "hub"
        self.assertIn("Installed", self.install())

    def test_not_in_catalog(self):
        self.assertIn("is not in the catalog", self.fails("install", "nobody"))

    def test_package_plugins_are_a_hint_only(self):
        package(self.pkg, extra={".claude-plugin/marketplace.json": json.dumps(
            {"name": "m", "plugins": [{"name": "analyst-skills", "source": "./plugins/a"}]})})
        out = self.install()
        self.assertIn("hub tools import set", out)
        self.assertIn("analyst-skills", out)
        self.assertFalse([c for c in self.hub.calls if c[:3] == ("tools", "import", "set")])
        self.assertFalse(os.path.exists(os.environ["HUB_CONFIG"]))

    def test_busy_agent_is_not_reloaded(self):
        def hub(*args, _orig=self.hub):
            code, out = _orig(*args)
            if args[:2] == ("session", "new"):
                _orig.sessions[args[2]]["state"] = "busy"
            return code, out
        sp.hub_run = hub
        out = self.install()
        self.assertIn("is still in a turn", out)
        self.assertNotIn(("session", "reload", "analyst"), self.hub.calls)


class Verify(Base):
    def test_verify_after_the_agent_wrote_late(self):
        self.hub.obey = False
        self.install()
        rec = self.state_file()["installed"]["analyst"]
        self.assertIn("does not match", self.fails("verify", "analyst"))
        os.makedirs(os.path.dirname(rec["agent_file"]), exist_ok=True)
        text = pathlib.Path(rec["profile_file"]).read_text(encoding="utf-8")
        with open(rec["agent_file"], "w", encoding="utf-8", newline="") as f:
            f.write(text.replace("\n", "  \r\n"))                      # CRLF and trailing spaces do not count
        out = self.run_cli("verify", "analyst")
        self.assertIn("matches the package profile", out)
        self.assertEqual(self.state_file()["installed"]["analyst"]["profile"], "ok")
        self.assertIn(("session", "reload", "analyst"), self.hub.calls)

    def test_mismatch_names_the_line(self):
        self.install()
        rec = self.state_file()["installed"]["analyst"]
        pathlib.Path(rec["agent_file"]).write_text("# analyst\nsomething else\n", encoding="utf-8")
        err = self.fails("verify", "analyst")
        self.assertIn("line 2", err)
        self.assertEqual(self.state_file()["installed"]["analyst"]["profile"], "pending")

    def test_missing_agent_file(self):
        self.hub.obey = False
        self.install()
        self.assertIn("the agent file is missing", self.fails("verify", "analyst"))

    def test_trial_has_nothing_to_verify(self):
        self.run_cli("install", "analyst", "--trial")
        self.assertIn("nothing to verify", self.run_cli("verify", "analyst"))


class Trial(Base):
    def test_trial_is_a_plain_session_with_claude_md_in_its_folder(self):
        out = self.run_cli("install", "analyst", "--trial")
        self.assertIn("trial: remove with specialists remove analyst", out)
        rec = self.state_file()["installed"]["analyst"]
        self.assertTrue(rec["trial"])
        self.assertEqual(rec["cwd"], os.path.join(self.state, "specialists", "trial", "analyst"))
        self.assertTrue(os.path.isfile(os.path.join(rec["cwd"], "CLAUDE.md")))
        new = next(c for c in self.hub.calls if c[:2] == ("session", "new"))
        self.assertNotIn("--agent", new)
        self.assertEqual(self.sends("analyst"), [])

    def test_trial_into_a_folder_with_claude_md_is_refused(self):
        cwd = os.path.join(self.tmp, "mine")
        os.makedirs(cwd)
        pathlib.Path(cwd, "CLAUDE.md").write_text("mine\n", encoding="utf-8")
        self.assertIn("already has a CLAUDE.md", self.fails("install", "analyst", "--trial", "--cwd", cwd))

    def test_remove_trial(self):
        self.run_cli("install", "analyst", "--trial")
        out = self.run_cli("remove", "analyst")
        self.assertIn("Trial analyst removed", out)
        self.assertIn(("session", "close", "analyst"), self.hub.calls)
        self.assertEqual(self.hub.sessions["analyst"]["state"], "removed")
        self.assertEqual(self.state_file()["installed"], {})

    def test_remove_trial_still_handing_over(self):
        self.run_cli("install", "analyst", "--trial")
        self.hub.close_to = "busy"
        self.assertIn("still handing over", self.fails("remove", "analyst"))
        self.assertIn("analyst", self.state_file()["installed"])

    def test_remove_trial_refused_asks_the_hub(self):
        self.run_cli("install", "analyst", "--trial")
        self.hub.remove_refused = True
        out = self.run_cli("remove", "analyst")
        self.assertIn("Record analyst removed", out)
        self.assertTrue(self.sends("hub"))


class UpdateRemove(Base):
    def setUp(self):
        super().setUp()
        commit(self.pkg)

    def test_same_version(self):
        self.install()
        self.assertIn("is the latest", self.run_cli("update", "analyst"))

    def test_update_hands_the_new_profile_and_keeps_local_sections(self):
        self.install()
        rec = self.state_file()["installed"]["analyst"]
        old = pathlib.Path(rec["agent_file"]).read_text(encoding="utf-8")
        local = f"{sp.LOCAL_OPEN}\nmy own line\n{sp.LOCAL_CLOSE}"
        pathlib.Path(rec["agent_file"]).write_text(old + "\n## Notes\n" + local + "\n", encoding="utf-8")
        package(self.pkg, man={**MAN, "version": "0.2.0"}, claude=CLAUDE + "\n## Notes\nnew text\n\n## End\nx\n")
        commit(self.pkg, "0.2.0")
        out = self.run_cli("update", "analyst")
        self.assertIn("analyst: 0.1.0 -> 0.2.0", out)
        self.assertIn("Local sections carried over", out)
        rec = self.state_file()["installed"]["analyst"]
        self.assertEqual((rec["version"], rec["profile"]), ("0.2.0", "ok"))
        text = pathlib.Path(rec["agent_file"]).read_text(encoding="utf-8")
        self.assertIn("new text", text)
        self.assertLess(text.index("my own line"), text.index("## End"))   # stays in its section
        self.assertTrue(os.path.isfile(sp.profile_path("analyst", ".prev")))

    def test_update_asks_new_tools(self):
        self.install("--tools", "none")
        tools = {"need": [{"id": "research", "why": "x"}, {"id": "brand-new", "why": "y"}], "optional": []}
        package(self.pkg, man={**MAN, "version": "0.2.0", "agent": {**MAN["agent"], "tools": tools}})
        commit(self.pkg, "0.2.0")
        self.hub.calls.clear()
        out = self.run_cli("update", "analyst")
        self.assertIn("New tools of the package", out)          # only tools new to the package, not ones skipped earlier
        self.assertIn("brand-new", out)
        self.assertNotIn(("tools", "grant", "analyst", "research"), self.hub.calls)

    def test_update_trial_rewrites_its_claude_md(self):
        self.run_cli("install", "analyst", "--trial")
        package(self.pkg, man={**MAN, "version": "0.2.0"}, claude=CLAUDE + "v2\n")
        commit(self.pkg, "0.2.0")
        out = self.run_cli("update", "analyst")
        self.assertIn("CLAUDE.md of the trial session rewritten", out)
        rec = self.state_file()["installed"]["analyst"]
        self.assertIn("v2", pathlib.Path(rec["agent_file"]).read_text(encoding="utf-8"))

    def test_remove_agent_asks_the_hub_and_keeps_the_file(self):
        self.install()
        rec = self.state_file()["installed"]["analyst"]
        out = self.run_cli("remove", "analyst")
        self.assertIn("Record analyst removed", out)
        self.assertTrue(os.path.isfile(rec["agent_file"]))
        self.assertFalse(os.path.exists(sp.profile_path("analyst")))
        self.assertIn("Remove agent analyst", self.sends("hub")[0][2])
        self.assertNotIn(("session", "remove", "analyst"), self.hub.calls)

    def test_remove_unknown(self):
        self.assertIn("is not installed", self.fails("remove", "analyst"))


class Adopt(Base):
    def setUp(self):
        super().setUp()
        commit(self.pkg)
        self.hub.sessions["designer"] = {"state": "idle", "session_id": "sid-designer", "kind": "work", "role": "agent"}
        os.makedirs(os.path.dirname(self.hub.agent_file("designer")))
        pathlib.Path(self.hub.agent_file("designer")).write_text("# designer by hand\n", encoding="utf-8")

    def test_adopt_records_and_leaves_the_file(self):
        out = self.run_cli("adopt", "designer", "analyst")
        self.assertIn("is now under the catalog", out)
        rec = self.state_file()["installed"]["designer"]
        self.assertTrue(rec["adopted"])
        self.assertEqual(pathlib.Path(rec["agent_file"]).read_text(encoding="utf-8"), "# designer by hand\n")
        self.assertEqual(self.sends(), [])
        self.assertIn("nothing to verify", self.run_cli("verify", "designer"))

    def test_adopt_refusals(self):
        self.assertIn("no session", self.fails("adopt", "ghost", "analyst"))
        self.hub.sessions["plain"] = {"state": "idle", "session_id": "sid-plain", "role": "worker"}
        self.assertIn("is not an agent", self.fails("adopt", "plain", "analyst"))
        self.hub.sessions["bare"] = {"state": "idle", "session_id": "sid-bare", "role": "agent"}
        self.assertIn("no agent file", self.fails("adopt", "bare", "analyst"))
        self.run_cli("adopt", "designer", "analyst")
        self.assertIn("is already installed", self.fails("adopt", "designer", "analyst"))

    def test_adopted_agent_updates_through_its_profile(self):
        self.run_cli("adopt", "designer", "analyst")
        package(self.pkg, man={**MAN, "version": "0.2.0"})
        commit(self.pkg, "0.2.0")
        out = self.run_cli("update", "designer")
        self.assertIn("designer: 0.1.0 -> 0.2.0", out)
        self.assertEqual(self.state_file()["installed"]["designer"]["profile"], "ok")
        self.assertEqual(pathlib.Path(sp.profile_path("designer", ".prev")).read_text(encoding="utf-8"),
                         "# designer by hand\n")


def head(root):
    return subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


class Pinned(Base):
    """The catalog pins every package to a full commit: install and update take exactly that commit."""

    def setUp(self):
        super().setUp()
        package(self.pkg, claude=CLAUDE + "first\n")
        commit(self.pkg, "first")
        self.first = head(self.pkg)
        package(self.pkg, man=dict(MAN, version="0.2.0"), claude=CLAUDE + "second\n")
        commit(self.pkg, "second")
        self.second = head(self.pkg)

    def pin(self, sha):
        with open(sp.CATALOG, "w", encoding="utf-8") as f:
            json.dump([{"name": "analyst", "repo": self.pkg, "version": "0.1.0", "commit": sha}], f)

    def test_install_takes_the_pinned_commit_not_the_head(self):
        self.pin(self.first)
        self.install()
        rec = self.state_file()["installed"]["analyst"]
        self.assertEqual(rec["version"], "0.1.0")
        self.assertEqual(rec["commit"], self.first)
        self.assertIn("first", pathlib.Path(self.hub.agent_file("analyst")).read_text(encoding="utf-8"))

    def test_a_pin_that_is_not_a_full_sha_is_refused(self):
        for bad in ("main", "90516c9", "HEAD", self.first[:12]):
            self.pin(bad)
            self.assertIn("full commit sha", self.fails("install", "analyst", "--cwd", os.path.join(self.tmp, "w")))
        self.assertEqual(self.hub.sessions, {})

    def test_a_pin_missing_in_the_repo_installs_nothing(self):
        self.pin("0" * 40)
        self.assertIn("cannot fetch package", self.fails("install", "analyst", "--cwd", os.path.join(self.tmp, "w")))
        self.assertEqual(self.hub.sessions, {})

    def test_update_moves_to_the_new_pin_even_when_the_version_is_the_same(self):
        self.pin(self.first)
        self.install()
        package(self.pkg, man=dict(MAN, version="0.1.0"), claude=CLAUDE + "third\n")   # the same version, other profile
        commit(self.pkg, "third")
        third = head(self.pkg)
        self.assertIn("is the latest", self.run_cli("update", "analyst"))
        self.pin(third)
        out = self.run_cli("update", "analyst")
        self.assertNotIn("is the latest", out)
        self.assertEqual(self.state_file()["installed"]["analyst"]["commit"], third)
        self.assertIn("third", pathlib.Path(self.hub.agent_file("analyst")).read_text(encoding="utf-8"))
        self.assertIn("is the latest", self.run_cli("update", "analyst"))

    def test_update_does_not_run_past_the_pin(self):
        self.pin(self.first)
        self.install()
        out = self.run_cli("update", "analyst")   # the repo head is 0.2.0, the pin still the first commit
        self.assertIn("is the latest", out)
        self.assertEqual(self.state_file()["installed"]["analyst"]["version"], "0.1.0")

    def test_update_follows_the_catalog_when_it_moves_the_package(self):
        self.pin(self.first)
        self.install()
        moved = package(os.path.join(self.tmp, "public-analyst"), man=dict(MAN, version="0.3.0"), claude=CLAUDE + "moved\n")
        commit(moved, "moved one")
        pin = head(moved)
        package(moved, man=dict(MAN, version="0.4.0"), claude=CLAUDE + "past the pin\n")
        commit(moved, "past the pin")   # the new repo's head: update must not run past the catalog's pin
        with open(sp.CATALOG, "w", encoding="utf-8") as f:
            json.dump([{"name": "analyst", "repo": moved, "version": "0.3.0", "commit": pin}], f)
        out = self.run_cli("update", "analyst")
        self.assertNotIn("is the latest", out)
        rec = self.state_file()["installed"]["analyst"]
        self.assertEqual((rec["repo"], rec["commit"], rec["version"]), (moved, pin, "0.3.0"))
        self.assertIn("moved", pathlib.Path(rec["profile_file"]).read_text(encoding="utf-8"))
        self.assertIn("is the latest", self.run_cli("update", "analyst"))

    def test_update_never_takes_the_old_repo_head_when_the_catalog_moved(self):
        self.pin(self.first)
        self.install()
        with open(sp.CATALOG, "w", encoding="utf-8") as f:   # moved to a repo that cannot be reached
            json.dump([{"name": "analyst", "repo": os.path.join(self.tmp, "gone"), "version": "0.9.0", "commit": "1" * 40}], f)
        self.assertIn("cannot fetch package", self.fails("update", "analyst"))
        rec = self.state_file()["installed"]["analyst"]
        self.assertEqual((rec["commit"], rec["version"]), (self.first, "0.1.0"))

    def test_a_package_installed_from_its_own_address_keeps_it(self):
        self.pin(self.first)
        self.run_cli("install", self.pkg, "--cwd", os.path.join(self.tmp, "work"))   # a folder, not the catalog entry
        rec = self.state_file()["installed"]["analyst"]
        self.assertEqual((rec["source"], rec["commit"]), ("own", self.second))   # its own head: no catalog pin
        with open(sp.CATALOG, "w", encoding="utf-8") as f:
            json.dump([{"name": "analyst", "repo": os.path.join(self.tmp, "gone"), "version": "0.9.0", "commit": "1" * 40}], f)
        self.assertIn("is the latest", self.run_cli("update", "analyst"))
        self.assertEqual(self.state_file()["installed"]["analyst"]["repo"], self.pkg)

    def test_adopt_records_the_pinned_commit(self):
        self.pin(self.first)
        self.hub.sessions["designer"] = {"state": "idle", "session_id": "sid-designer", "kind": "work", "role": "agent"}
        os.makedirs(os.path.dirname(self.hub.agent_file("designer")))
        pathlib.Path(self.hub.agent_file("designer")).write_text("# by hand\n", encoding="utf-8")
        self.run_cli("adopt", "designer", "analyst")
        self.assertEqual(self.state_file()["installed"]["designer"]["commit"], self.first)

    def git_calls(self, work):
        """argv of every git run while `work` goes."""
        calls, real = [], subprocess.run

        def spy(cmd, *a, **kw):
            if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == "git":
                calls.append(list(cmd))
            return real(cmd, *a, **kw)
        subprocess.run = spy
        try:
            work()
        finally:
            subprocess.run = real
        return calls

    def test_the_address_always_follows_two_dashes(self):
        for sha in (self.first, ""):    # a pinned fetch and a plain clone
            self.pin(sha)
            calls = self.git_calls(lambda: sp.fetch(self.pkg, sha)[1] and shutil.rmtree(sp.fetch(self.pkg, sha)[1], True))
            talking = [c for c in calls if any(x in c for x in ("clone", "fetch"))]
            self.assertTrue(talking)
            for c in talking:
                src = os.path.abspath(self.pkg)
                self.assertIn(src, c)
                self.assertEqual(c[c.index(src) - 1], "--", c)

    def test_an_address_that_looks_like_an_option_is_not_an_option(self):
        marker = os.path.join(self.tmp, "ran")
        evil = f"--upload-pack=touch {marker}"
        for sha in (self.first, ""):
            with self.assertRaises(SystemExit):
                sp.fetch(evil, sha)
            self.assertFalse(os.path.exists(marker))


class HubCommand(unittest.TestCase):
    """The hub command: SPECIALISTS_HUB first, then shutil.which (hub.cmd on Windows), then HUB_NESTED_*."""
    def setUp(self):
        self.old = sp.HUB, sp.shutil.which, {k: os.environ.get(k) for k in ("HUB_NESTED_PYTHON", "HUB_NESTED_HUB")}
        sp.HUB = ""
        self.addCleanup(self.unpatch)

    def unpatch(self):
        sp.HUB, sp.shutil.which = self.old[0], self.old[1]
        for k, v in self.old[2].items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_which_path_wins_over_bare_name(self):
        cmd = r"C:\hub\nested\hub.cmd"
        sp.shutil.which = lambda name: cmd if name == "hub" else None
        self.assertEqual(sp.hub_cmd(), [cmd])

    def test_env_override_wins_over_which(self):
        sp.HUB = "/opt/my-hub"
        sp.shutil.which = lambda name: r"C:\hub.cmd"
        self.assertEqual(sp.hub_cmd(), ["/opt/my-hub"])

    def test_nested_pair_when_not_in_path(self):
        sp.shutil.which = lambda name: None
        os.environ["HUB_NESTED_PYTHON"], os.environ["HUB_NESTED_HUB"] = "C:/py/python.exe", "C:/hub/bin/hub"
        self.assertEqual(sp.hub_cmd(), ["C:/py/python.exe", "C:/hub/bin/hub"])

    def test_nested_needs_both(self):
        sp.shutil.which = lambda name: None
        os.environ["HUB_NESTED_PYTHON"] = "C:/py/python.exe"
        os.environ.pop("HUB_NESTED_HUB", None)
        self.assertEqual(sp.hub_cmd(), ["hub"])

    def test_hub_run_uses_resolved_command(self):
        seen = []
        old = sp.subprocess.run
        sp.subprocess.run = lambda cmd, **kw: seen.append(cmd) or type("R", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
        self.addCleanup(setattr, sp.subprocess, "run", old)
        cmd = r"C:\hub\nested\hub.cmd"
        sp.shutil.which = lambda name: cmd
        self.assertEqual(sp.hub_run("status", "--json"), (0, "ok"))
        self.assertEqual(seen, [[cmd, "status", "--json"]])


class Utf8Streams(unittest.TestCase):
    def test_non_utf8_streams_are_switched(self):
        raw_out, raw_err = io.BytesIO(), io.BytesIO()
        out = io.TextIOWrapper(raw_out, encoding="cp1251", write_through=True)
        err = io.TextIOWrapper(raw_err, encoding="cp866", write_through=True)
        old = sp.sys.stdout, sp.sys.stderr
        sp.sys.stdout, sp.sys.stderr = out, err
        try:
            sp.utf8_streams()
            print("Catalog \u2713")
            print("Error \u2713", file=sp.sys.stderr)
        finally:
            sp.sys.stdout, sp.sys.stderr = old
        self.assertEqual(raw_out.getvalue().decode("utf-8").replace("\r\n", "\n"), "Catalog \u2713\n")
        self.assertEqual(raw_err.getvalue().decode("utf-8").replace("\r\n", "\n"), "Error \u2713\n")

    def test_streams_without_reconfigure_are_left_alone(self):
        old = sp.sys.stdout, sp.sys.stderr
        sp.sys.stdout, sp.sys.stderr = io.StringIO(), io.StringIO()
        try:
            sp.utf8_streams()
        finally:
            sp.sys.stdout, sp.sys.stderr = old

    def test_main_switches_streams(self):
        seen = []
        old = sp.utf8_streams
        sp.utf8_streams = lambda: seen.append(1)
        self.addCleanup(setattr, sp, "utf8_streams", old)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            sp.main([])
        self.assertEqual(seen, [1])


class PageFiles(unittest.TestCase):
    """The plugin page: the file from the manifest exists; every catalog package has what the view shows."""

    def test_web_and_catalog_rows(self):
        root = pathlib.Path(__file__).resolve().parent.parent
        man = json.loads((root / "hub-plugin.json").read_text(encoding="utf-8"))
        self.assertTrue((root / man["web"]).is_file())
        self.assertIn("sidebar.group", (root / man["web"]).read_text(encoding="utf-8"))
        for p in json.loads((root / "specialists.json").read_text(encoding="utf-8")):
            self.assertTrue(p["name"] and p["repo"] and p["version"] and p["icon"] and p["about"], p)

    def test_every_catalog_entry_pins_a_full_commit(self):
        root = pathlib.Path(__file__).resolve().parent.parent
        for p in json.loads((root / "specialists.json").read_text(encoding="utf-8")):
            self.assertRegex(p.get("commit", ""), r"^([0-9a-f]{40}|[0-9a-f]{64})$", p["name"])

    def test_nothing_names_the_slot_only_our_core_has(self):
        root = pathlib.Path(__file__).resolve().parent.parent
        man = json.loads((root / "hub-plugin.json").read_text(encoding="utf-8"))
        for text in (man["description"], man["i18n"]["ru"]["description"], man.get("why", ""),
                     (root / "README.md").read_text(encoding="utf-8")):
            self.assertNotIn("sidebar.group", text)
            self.assertNotRegex(text, r'the "\+"|"\+" ')

    def test_manifest_texts_fit_the_catalog(self):
        root = pathlib.Path(__file__).resolve().parent.parent
        man = json.loads((root / "hub-plugin.json").read_text(encoding="utf-8"))
        for text in (man["description"], man["i18n"]["ru"]["description"]):
            self.assertLessEqual(len(text), 300, text)

    def test_no_private_traces_in_the_plugin(self):
        root = pathlib.Path(__file__).resolve().parent.parent
        names = [p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts and p.suffix in
                 (".md", ".json", ".py", ".js", ".mjs", "")]
        for path in names:
            if path.name in ("test_specialists.py", "specialists", "public_branch.py"):   # these hold the leak patterns themselves
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for kind, rx in sp.LEAKS:
                self.assertIsNone(rx.search(text), f"{path}: {kind}")


MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
mloader = importlib.machinery.SourceFileLoader("specialists_process", MAIN)
proc = importlib.util.module_from_spec(importlib.util.spec_from_loader("specialists_process", mloader))
mloader.exec_module(proc)


class Process(unittest.TestCase):
    """The plugin process: version check for the "Check for updates" button; all in a temp folder, no network."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.old = (proc.STATE, proc.CATALOG, proc.STATUS)
        proc.STATE = os.path.join(self.tmp, "state")
        proc.CATALOG = os.path.join(self.tmp, "specialists.json")
        proc.STATUS = os.path.join(self.tmp, "status.json")
        self.addCleanup(lambda: setattr(proc, "STATE", self.old[0]) or setattr(proc, "CATALOG", self.old[1])
                        or setattr(proc, "STATUS", self.old[2]))
        self.installed({"analyst": ("analyst", "0.1.0"), "writer": ("writer", "0.3.0")})

    def installed(self, agents):
        os.makedirs(os.path.join(proc.STATE, "specialists"), exist_ok=True)
        with open(os.path.join(proc.STATE, "specialists", "state.json"), "w", encoding="utf-8") as f:
            json.dump({"installed": {a: {"package": p, "version": v, "repo": "https://example.invalid/" + p}
                                     for a, (p, v) in agents.items()}}, f)

    def test_newer_compares_numbers_not_strings(self):
        self.assertTrue(proc.newer("0.10.0", "0.9.0"))
        self.assertFalse(proc.newer("0.9.0", "0.10.0"))
        self.assertFalse(proc.newer("0.1.0", "0.1.0"))
        self.assertFalse(proc.newer("", "0.1.0"))
        self.assertFalse(proc.newer("0.2.0", ""))
        self.assertTrue(proc.newer("beta", "0.1.0"))   # not numbers: a different string is newer

    def test_check_marks_only_the_lagging_package(self):
        answers = {"https://example.invalid/analyst": ("0.2.0", ""), "https://example.invalid/writer": ("0.3.0", "")}
        proc.check_all(now=100, probe=lambda repo, commit="": answers[repo])
        status = proc.build("c-1")
        self.assertEqual(status["req"], "c-1")
        self.assertEqual(status["checked_at"], 100)
        self.assertEqual(status["rows"]["analyst"], {"package": "analyst", "installed": "0.1.0", "latest": "0.2.0",
                                                     "update": True, "error": ""})
        self.assertFalse(status["rows"]["writer"]["update"])

    def test_one_package_failing_does_not_hide_the_rest(self):
        def probe(repo, commit=""):
            return ("", "Could not resolve host") if repo.endswith("analyst") else ("0.4.0", "")
        proc.check_all(now=1, probe=probe)
        rows = proc.build()["rows"]
        self.assertEqual(rows["analyst"]["error"], "Could not resolve host")
        self.assertFalse(rows["analyst"]["update"])
        self.assertTrue(rows["writer"]["update"])

    def test_the_catalog_address_and_pin_win_for_a_catalog_package(self):
        with open(proc.CATALOG, "w", encoding="utf-8") as f:
            json.dump([{"name": "analyst", "repo": "https://example.invalid/moved", "commit": "1" * 40}], f)
        seen = []
        proc.check_all(now=1, probe=lambda repo, commit="": seen.append((repo, commit)) or ("0.1.0", ""))
        self.assertIn(("https://example.invalid/moved", "1" * 40), seen)   # where the catalog moved it, at its pin
        self.assertNotIn("https://example.invalid/analyst", [r for r, _ in seen])   # never the old repo's head

    def test_a_package_of_ones_own_address_is_checked_there(self):
        with open(os.path.join(proc.STATE, "specialists", "state.json"), "w", encoding="utf-8") as f:
            json.dump({"installed": {"analyst": {"package": "analyst", "version": "0.1.0", "source": "own",
                                                 "repo": "https://example.invalid/mine"}}}, f)
        with open(proc.CATALOG, "w", encoding="utf-8") as f:
            json.dump([{"name": "analyst", "repo": "https://example.invalid/moved", "commit": "1" * 40}], f)
        seen = []
        proc.check_all(now=1, probe=lambda repo, commit="": seen.append((repo, commit)) or ("0.1.0", ""))
        self.assertEqual(seen, [("https://example.invalid/mine", "")])

    def test_installed_version_follows_state_without_a_new_check(self):
        proc.check_all(now=1, probe=lambda repo, commit="": ("0.2.0", ""))
        self.assertTrue(proc.build()["rows"]["analyst"]["update"])
        self.installed({"analyst": ("analyst", "0.2.0"), "writer": ("writer", "0.3.0")})   # specialists update ran
        self.assertFalse(proc.build()["rows"]["analyst"]["update"])

    def test_requests_are_only_the_owners_check_posts(self):
        batch = [{"id": "p1", "text": "check c-1", "by": "owner"}, {"id": "p2", "text": "check c-2", "by": "agent"},
                 {"id": "p3", "text": "hello", "by": "owner"}, {"id": "p4", "text": "check c-3 and more", "by": "owner"}]
        self.assertEqual(proc.requests(batch), ["c-1"])   # another author and extra text do not count
        self.assertEqual(proc.seq({"id": "p42"}), 42)
        self.assertEqual(proc.seq({"id": "x"}), 0)

    def test_publish_writes_only_on_change(self):
        proc.publish("a")
        first = os.stat(proc.STATUS).st_mtime_ns
        proc.publish("a")
        self.assertEqual(os.stat(proc.STATUS).st_mtime_ns, first)
        proc.publish("b")
        with open(proc.STATUS, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["req"], "b")

    def test_latest_version_from_a_git_repo_and_a_plain_folder(self):
        repo = package(os.path.join(self.tmp, "repo"), man=dict(MAN, version="0.5.0"))
        commit(repo)
        self.assertEqual(proc.latest_version(repo), ("0.5.0", ""))
        plain = package(os.path.join(self.tmp, "plain"), man=dict(MAN, version="0.6.1"))
        self.assertEqual(proc.latest_version(plain), ("0.6.1", ""))
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        self.assertEqual(proc.latest_version(empty)[0], "")
        version, why = proc.latest_version(os.path.join(self.tmp, "nowhere"))
        self.assertEqual(version, "")
        self.assertTrue(why)


class ProcessPinned(Process):
    """The update check follows the catalog's pin and shows what an update would change in the profile."""

    def setUp(self):
        super().setUp()
        self.repo = package(os.path.join(self.tmp, "repo"), claude=CLAUDE + "one\nkeep\n")
        commit(self.repo, "one")
        self.one = head(self.repo)
        package(self.repo, man=dict(MAN, version="0.2.0"), claude=CLAUDE + "two\nkeep\n")
        commit(self.repo, "two")
        self.two = head(self.repo)
        package(self.repo, man=dict(MAN, version="0.3.0"), claude=CLAUDE + "three\nkeep\n")
        commit(self.repo, "three")

    def pin(self, sha):
        with open(proc.CATALOG, "w", encoding="utf-8") as f:
            json.dump([{"name": "analyst", "repo": self.repo, "version": "0.1.0", "commit": sha}], f)

    def record(self, **extra):
        os.makedirs(os.path.join(proc.STATE, "specialists"), exist_ok=True)
        with open(os.path.join(proc.STATE, "specialists", "state.json"), "w", encoding="utf-8") as f:
            json.dump({"installed": {"analyst": dict({"package": "analyst", "version": "0.1.0", "repo": self.repo}, **extra)}}, f)

    def test_latest_version_is_read_at_the_pin_not_at_the_head(self):
        self.assertEqual(proc.latest_version(self.repo, self.two), ("0.2.0", ""))
        self.assertEqual(proc.latest_version(self.repo), ("0.3.0", ""))
        version, why = proc.latest_version(self.repo, "f" * 40)
        self.assertEqual(version, "")
        self.assertTrue(why)

    def test_a_pinned_package_must_be_a_git_repo(self):
        plain = package(os.path.join(self.tmp, "plain"), man=dict(MAN, version="0.6.1"))
        self.assertEqual(proc.latest_version(plain, self.one)[0], "")

    def test_the_check_asks_at_the_pin(self):
        self.pin(self.two)
        self.record(commit=self.one)
        proc.check_all(now=1)
        row = proc.build()["rows"]["analyst"]
        self.assertEqual(row["latest"], "0.2.0")
        self.assertTrue(row["update"])

    def test_same_version_other_commit_is_still_an_update_with_its_preview(self):
        package(self.repo, man=dict(MAN, version="0.1.0"), claude=CLAUDE + "other\nkeep\n",
                extra={"plugins/x/.claude-plugin/plugin.json": "{}"})
        commit(self.repo, "same version")
        pin = head(self.repo)
        self.pin(pin)
        self.record(commit=self.one)
        proc.check_all(now=1)
        row = proc.build()["rows"]["analyst"]
        self.assertTrue(row["update"])
        ch = row["changes"]
        self.assertEqual((ch["base"], ch["to"]), (self.one, pin))
        self.assertTrue(ch["profile"]["known"])
        self.assertIn("+other", ch["profile"]["lines"])
        self.assertIn("-one", ch["profile"]["lines"])
        self.assertNotIn("+keep", ch["profile"]["lines"])

    def test_changes_name_tools_and_plugins(self):
        self.pin(self.two)
        man = dict(MAN, version="0.2.0", agent=dict(MAN["agent"], tools={"need": [{"id": "figma", "why": "x"}], "optional": []}))
        package(self.repo, man=man, claude=CLAUDE)
        commit(self.repo, "tools")
        pin = head(self.repo)
        ch = proc.changes_of(self.repo, pin, {"package": "analyst", "version": "0.1.0", "commit": self.one,
                                              "tool_ids": ["research"], "plugins": []})
        self.assertEqual(ch["tools"]["added"], ["figma"])
        self.assertEqual(ch["tools"]["removed"], ["research"])

    def test_a_record_without_a_commit_has_no_moved_flag_and_no_diff(self):
        self.pin(self.two)
        self.record()    # installed by 0.9.0: no commit recorded
        proc.check_all(now=1)
        row = proc.build()["rows"]["analyst"]
        self.assertTrue(row["update"])           # 0.1.0 < 0.2.0 by version
        self.assertNotIn("changes", row)

    def test_a_preview_for_another_base_is_not_shown(self):
        self.pin(self.two)
        self.record(commit=self.one)
        proc.check_all(now=1)
        self.record(commit=self.two)              # updated meanwhile: the old preview is stale
        self.assertNotIn("changes", proc.build()["rows"]["analyst"])

    def test_git_gets_the_address_after_two_dashes(self):
        marker = os.path.join(self.tmp, "ran")
        evil = f"--upload-pack=touch {marker}"
        self.assertEqual(proc.latest_version(evil)[0], "")
        self.assertEqual(proc.latest_version(evil, self.one)[0], "")
        self.assertIsNone(proc.changes_of(evil, self.one, {"commit": self.two}))
        self.assertFalse(os.path.exists(marker))


if __name__ == "__main__":
    unittest.main()
