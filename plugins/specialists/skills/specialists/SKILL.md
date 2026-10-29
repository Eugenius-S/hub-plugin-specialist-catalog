---
name: specialists
description: Install a ready-made specialist from the catalog into the hub (an analyst and others), update or remove it. Use when the owner asks "install specialist X", "what is in the specialists catalog", "update the specialist".
---

# Specialists catalog

The hub or the owner runs the command: the agent is created by `hub session new`; from a working session it is only a
request to the hub.

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/specialists" list
python3 "${CLAUDE_PLUGIN_ROOT}/bin/specialists" install <name|folder|git-url> [--name other] [--tools need|all|none] [--trial]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/specialists" verify <agent>
python3 "${CLAUDE_PLUGIN_ROOT}/bin/specialists" adopt <agent> [<package>]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/specialists" update <agent>
python3 "${CLAUDE_PLUGIN_ROOT}/bin/specialists" remove <agent>
```

- "Package not accepted": the reason is in the output (manifest fields, leaks). The package's author fixes it, not you.
- "Name taken": pick another name with `--name`; no duplicates.
- The profile: install and update ask the agent to put the package profile into its agent file and check it. `NOT READY`
  means the file does not match yet: when the agent has written it, run `verify <agent>`.
- Tools: risky ones wait for the owner's yes (the card is already with the owner); tools missing from the hub's catalog are
  listed in the output, pass them to the owner.
- The package's own plugins are not connected by the command: it prints the steps (`hub tools import set`,
  `hub tools grant`), pass them to the owner.
- `--trial`: a trial install, a plain session (not an agent) with the package's CLAUDE.md in its folder; `remove` removes it
  completely (close, wait for sleep, remove) without the owner.
- `adopt`: put a live agent installed by hand under the catalog; its CLAUDE.md and tools are left as they are.
- `update` keeps the section between `<!-- specialists:local -->` and `<!-- /specialists:local -->` in the new profile.
- `remove` drops the record; the hub closes and removes the session (retiring an agent is the owner's call).
