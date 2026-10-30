# specialists: a catalog of ready-made agents

A plugin for [Agents Hub](https://github.com/flagman/agents-hub-core) (topic `agents-hub-plugin`): ready-made agents as
packages. A specialist package is a plain git repo: `hub-plugin.json` (`kind: "specialist"`, name, version, icon,
description, working folder, required and optional tools, the file of eval cases), the agent's `CLAUDE.md` and the cases.
The catalog holds only links (`specialists.json`: name, repo, version), so packages do not depend on it: if the hub learns to
install them by itself, the catalog goes and the packages stay.

```
specialists list                                    what the catalog offers and what is installed
specialists install <name|folder|git-url> [--name N] [--cwd DIR] [--tools need|all|none] [--trial]
specialists verify <agent>                          compare the agent file with the package profile again
specialists adopt <agent> [<package|folder|git-url>] put an agent installed by hand under the catalog (record only)
specialists update <agent>                          a new package version: the new profile goes to the agent and is checked
specialists remove <agent>                          drop the record; the hub removes the session (a trial one: here)
```

**install** checks the package (manifest fields, hub version, `CLAUDE.md`, cases; leaks such as keys, personal paths, cloud
drives or task numbers are a refusal with the reason), creates the agent (`hub session new --agent`) and hands it its
profile: `CLAUDE.md` of the package with `{AGENT_FILE}` and `{CWD}` filled in goes to `<hub state>/specialists/profiles/`,
and the agent is asked to put it into its own agent file. The plugin does not write the agent file: the agent does, and
the plugin reads it back. Equal to the profile: the agent is restarted with it and marked ready. Not equal within the wait
(5 min): `NOT READY` with the first difference and the command to run later, `specialists verify <agent>`. Then the tools
are requested from the hub (`hub tools grant`); a risky tool waits for the owner's yes (a card). A taken name is a refusal
with a hint to use `--name`. Only the hub or the owner installs.

**adopt** puts under the catalog an agent that already lives in the hub but was installed around it (by hand or on another
machine): a record like install's (package, version, agent file, folder). The agent's `CLAUDE.md` and tools are left as
they are, the session is not restarted. The default package is the one with the agent's name. Refused: no such session, it
is not an agent, no agent file, the agent is already installed, the package is not accepted. After adopt, `update` works as
usual.

**Local section.** What must survive an update and is not part of the package (machine paths, local projects) the agent
keeps between `<!-- specialists:local -->` and `<!-- /specialists:local -->`: update carries this section into the new
profile, so the agent gets one whole file to put in place.

**Which repo update follows.** The address recorded at install: a hub that installed a package from its own repo
stays on it even when the catalog lists a package of that name elsewhere. The catalog's pinned commit applies only to
the catalog's own address; an agent on another address gets its repo head.

**--trial** is a trial install (try a specialist and remove it without the owner): instead of an agent, a plain session is
created (`hub session new` without `--agent`, role worker), and the package's `CLAUDE.md` is put into its folder,
`<hub state>/specialists/trial/<name>` or `--cwd` (someone else's `CLAUDE.md` there is a refusal). **remove** of a trial
session closes it, waits for it to fall asleep, removes it and drops the record; the folder stays. Not asleep within 20 s:
the record stays, try again later.

**The package's own plugins** (Claude Code skills: `.claude-plugin/marketplace.json` and `plugins/<plugin>` inside the
package) are not connected by this plugin: it does not write the hub's settings. install, update and adopt print the steps
for the owner: add the package as a Claude Code marketplace, `hub tools import set <marketplace>`,
`hub tools grant <agent> <plugin>@<marketplace>`.

## On the hub page

The catalog is in the ☰ menu ("Specialists catalog"). The plugin adds a shortcut only to a slot the page really offers (it
reads the page's slot list first); on a page without such a slot there is just the menu entry, and nothing fails. The catalog
lists packages from `specialists.json` with icon, description and version. An agent with that name exists: "✓ Installed"; otherwise "Install", which asks the hub to run
`specialists install <name>` (the hub installs, not the page). The button waits until the agent shows up.

Removing: the trash icon on an installed card. A confirmation on the card says what goes away (the agent leaves the list;
files and past chats stay on disk). The page then asks the hub to run `specialists remove <name>` and to retire and remove
the session, a request from the owner like "Install". If the agent is still there after 10 minutes, the card says so.

"Not in the catalog": an agent in the hub (role agent, not built in) without a package in `specialists.json`. Its card has
"Share" (after a confirmation the page asks the hub to pack the agent as a package and add it to the catalog) and the trash
(it only removes the session: the agent file and the chat stay on disk).

Built-in agents of the hub (the core marks them `system` in the snapshot) are listed with a "Built in" label and no buttons:
the core does not let them go.

"Check for updates" asks the plugin process to compare the installed version of every package with the latest one in its
repo; where a newer one is out (or the repo head moved off the pinned commit), "✓ Installed" turns into "Update". "Update"
first opens a card with what changes in the profile (lines added and removed in `CLAUDE.md` with the first lines of the diff,
tools and plugins added or removed); only "Update" on that card sends the request to the hub (`specialists update <name>`).

Page strings are English and Russian, by the hub's language.

## What it reads, writes and sends

- **Writes** only its own files: `<hub state>/specialists/` (`state.json`: what is installed, version, agent name;
  `profiles/`: the profile handed to each agent; `trial/`: folders of trial sessions) and `status.json` next to `main.py`
  (the result of "Check for updates"). It does not write `hub.json`, `~/.claude.json`, agent files or any other
  component's files.
- **Reads**: the catalog (`specialists.json` or the `catalog` setting), the hub's snapshot (`hub status --json`), the agent
  file it asked the agent to write, and its own feed channel on the hub page (`127.0.0.1`, `/api/feed`) for "Check for
  updates" requests posted by the owner.
- **Network**: `git fetch` / `git clone` of package repos listed in the catalog: exactly the pinned commit (shallow), for
  install, update, the update check and the preview of what an update changes. The repo address always goes after `--`.
  Nothing else leaves the machine.
- **Sends** through `hub` commands only: `hub session new` (the agent or trial session), `hub send <agent>` (the request
  to write its profile), `hub session reload`, `hub tools grant` (a risky tool goes to the owner as a card),
  `hub send hub` (removing a session), and for a trial session `hub session close` / `hub session remove`. The page sends
  the owner's button presses to the hub as messages (`/api/send`), the same as typing them.

## Checks

Page: `node --test tests/*.test.mjs`. CLI and process: `python3 -m unittest discover -s tests` (with the hub's code on
`PYTHONPATH`).

`tools/public_branch.py` builds the public branch of a package from its working branch (translation memory, leak check);
see its docstring.

Icon (icon.png): [3D Fluency](https://icons8.com/icons/3d-fluency) by Icons8; menu icon (icon.svg): Material Outlined.

## Not in the short description (the catalog limit is 300 characters)

- A specialist package: profile, `CLAUDE.md`, tools, eval cases; `specialists install <name>` creates the agent, hands it
  its profile, checks the agent file and asks for the tools.
- Every catalog entry pins a full commit (`commit` in `specialists.json`): install and update take exactly that commit,
  not the branch head. `update` brings the pinned version through the same check; the local section of the agent file is kept.
- On the page: install, remove with a confirmation, "Share" for agents without a package, built-in agents without buttons.
- "Check for updates" compares installed and latest versions and offers "Update" after a confirmation card with the changes.
