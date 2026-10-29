"""tools/public_branch.py: the public branch of a package is main's tree through the translation memory."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import public_branch as pb  # noqa: E402

RU = "Привет"          # a word of the source language
RU2 = "Мир"


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, check=True, text=True,
                          encoding="utf-8").stdout


class PublicBranch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "pkg")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "test")
        self.deny = os.path.join(self.tmp.name, "deny.txt")
        with open(self.deny, "w", encoding="utf-8") as f:
            f.write("# private names\nacme-internal\n")
        self.write({
            "README.md": f"# Package\n\n{RU} block\n\nPlain block\n",
            "run.py": f"x = 1  # {RU}\ny = 2\n",
            "hub-plugin.json": json.dumps({"name": "pkg", "description": f"{RU2}",
                                           "i18n": {"ru": {"description": RU2}}}, ensure_ascii=False),
            "notes/private.md": "acme-internal only\n",
        })

    def write(self, files):
        for path, text in files.items():
            p = os.path.join(self.repo, path)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "work")

    def run_cmd(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            pb.main(list(argv))
        return out.getvalue()

    def todo(self):
        path = os.path.join(self.tmp.name, "todo.json")
        self.run_cmd("todo", self.repo, "--deny", self.deny, "--out", path)
        with open(path, encoding="utf-8") as f:
            return path, json.load(f)

    def fill(self, path, items, extra=None):
        public = {f"{RU} block": "Hello block", f"x = 1  # {RU}": "x = 1  # hello", RU2: "World",
                  "acme-internal only\n": "", "acme-internal": ""}
        for i in items:
            i["public"] = public[i["text"]]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dict(units=items, **(extra or {})), f, ensure_ascii=False)
        self.run_cmd("learn", self.repo, path)

    def show(self, path):
        return git(self.repo, "show", f"{pb.PUBLIC}:{path}")

    def test_todo_lists_only_units_that_need_work_and_i18n_is_left_alone(self):
        _, items = self.todo()
        self.assertEqual(sorted(i["text"] for i in items),
                         sorted([f"{RU} block", f"x = 1  # {RU}", RU2, "acme-internal only\n"]))

    def test_build_refuses_while_anything_is_untranslated(self):
        with self.assertRaises(SystemExit) as e:
            self.run_cmd("build", self.repo, "--deny", self.deny)
        self.assertIn("untranslated", str(e.exception))
        self.assertEqual(git(self.repo, "branch", "--list", pb.PUBLIC), "")

    def test_build_writes_an_orphan_public_branch_from_the_memory(self):
        path, items = self.todo()
        self.fill(path, items, {"drop": ["notes/*"]})
        self.run_cmd("build", self.repo, "--deny", self.deny)
        self.assertEqual(self.show("README.md"), "# Package\n\nHello block\n\nPlain block\n")
        self.assertEqual(self.show("run.py"), "x = 1  # hello\ny = 2\n")
        manifest = json.loads(self.show("hub-plugin.json"))
        self.assertEqual(manifest["description"], "World")
        self.assertEqual(manifest["i18n"]["ru"]["description"], RU2, "translations of the manifest stay")
        self.assertNotIn("notes/private.md", git(self.repo, "ls-tree", "-r", "--name-only", pb.PUBLIC))
        self.assertEqual(git(self.repo, "rev-list", "--count", pb.PUBLIC).strip(), "1", "none of main's history")
        self.assertEqual(git(self.repo, "rev-parse", "--abbrev-ref", "HEAD").strip(), "main", "working copy untouched")
        self.assertIn("unchanged", self.run_cmd("build", self.repo, "--deny", self.deny), "a rebuild is a no-op")

    def test_a_new_main_reuses_the_memory_and_asks_only_for_new_units(self):
        path, items = self.todo()
        self.fill(path, items, {"drop": ["notes/*"]})
        self.write({"run.py": f"x = 1  # {RU}\ny = 3  # {RU2}\n"})
        _, items = self.todo()
        self.assertEqual([i["text"] for i in items], [f"y = 3  # {RU2}"])

    def test_a_leak_left_in_the_result_blocks_the_build(self):
        self.write({"notes/private.md": "x\n", "docs/a.md": "see /" + "Users/someone/files and d" + "123456\n"})
        path, items = self.todo()
        self.fill(path, items)
        with self.assertRaises(SystemExit) as e:
            self.run_cmd("build", self.repo, "--deny", self.deny)
        self.assertIn("personal path", str(e.exception))
        self.assertIn("task or message number", str(e.exception))

    def test_a_dropped_unit_leaves_no_hole(self):
        self.write({"notes/private.md": "Keep\n\nacme-internal only\n\nEnd\n"})
        path, items = self.todo()
        for i in items:
            if i["text"] == "acme-internal only":
                i["text"] = "acme-internal only\n"
        self.fill(path, items)
        self.run_cmd("build", self.repo, "--deny", self.deny)
        self.assertEqual(self.show("notes/private.md"), "Keep\n\nEnd\n")

    def test_an_emptied_json_string_drops_its_list_item(self):
        self.write({"hub-plugin.json": json.dumps({"name": "pkg", "tools": [
            {"id": "acme-internal", "why": "x"}, {"id": "figma", "why": "y"}]})})
        path, items = self.todo()
        self.fill(path, items, {"drop": ["notes/*"]})
        self.run_cmd("build", self.repo, "--deny", self.deny)
        self.assertEqual(json.loads(self.show("hub-plugin.json"))["tools"], [{"id": "figma", "why": "y"}])

    def test_a_memory_entry_for_a_plain_unit_still_applies(self):
        self.write({"hub-plugin.json": json.dumps({"name": "pkg", "tools": [
            {"id": "our-tool", "why": "x"}, {"id": "figma", "why": "y"}]})})
        path, items = self.todo()
        self.fill(path, items, {"drop": ["notes/*"]})
        self.assertIn("our-tool", self.run_cmd("build", self.repo, "--deny", self.deny) + self.show("hub-plugin.json"),
                      "plain English is left alone without a memory entry")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"units": [{"text": "our-tool", "public": ""}]}, f)
        self.run_cmd("learn", self.repo, path)
        self.run_cmd("build", self.repo, "--deny", self.deny)
        self.assertEqual(json.loads(self.show("hub-plugin.json"))["tools"], [{"id": "figma", "why": "y"}])

    def test_private_blocks_stay_in_main_and_never_reach_the_public_branch(self):
        self.write({"notes/private.md": "x\n",
                    "CLAUDE.md": "# Agent\n\nRule with a neutral example.\n\n<!-- release:private -->\n"
                                 "Our spring sale at $99 worked.\n<!-- /release:private -->\n\nEnd\n",
                    "build.py": "a = 1\n# release:private\nb = 'client'\n# /release:private\nc = 3\n"})
        path, items = self.todo()
        self.fill(path, items, {"drop": ["notes/*"]})
        self.run_cmd("build", self.repo, "--deny", self.deny)
        self.assertEqual(self.show("CLAUDE.md"), "# Agent\n\nRule with a neutral example.\n\nEnd\n")
        self.assertEqual(self.show("build.py"), "a = 1\nc = 3\n")
        self.assertIn("$99", git(self.repo, "show", "main:CLAUDE.md"), "main keeps it for this hub's agents")

    def test_an_unclosed_private_block_blocks_the_build(self):
        self.write({"notes/private.md": "x\n", "CLAUDE.md": "# Agent\n\n<!-- release:private -->\nOur prices\n"})
        path, items = self.todo()
        self.fill(path, items, {"drop": ["notes/*"]})
        with self.assertRaises(SystemExit) as e:
            self.run_cmd("build", self.repo, "--deny", self.deny)
        self.assertIn("unclosed release:private", str(e.exception))



if __name__ == "__main__":
    unittest.main()
