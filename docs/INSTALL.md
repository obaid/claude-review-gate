# Installation guide

## Requirements

- **Claude Code**, recent enough to support plugins (`/plugin` works).
- **python3** on your `PATH`. The hook uses only the standard library. macOS and Linux are tested. On Windows, run Claude Code under WSL, or make sure `python3` resolves.
- **git**.
- **gh** (GitHub CLI), signed in, for the PR flow: `gh auth login`.

## Install for yourself

Inside Claude Code:

```
/plugin marketplace add obaid/claude-review-gate
/plugin install review-gate@review-gate
```

Or from a terminal:

```
claude plugin marketplace add obaid/claude-review-gate
claude plugin install review-gate@review-gate
```

Then **restart Claude Code**. Hooks load when a session starts.

### Check it's working

1. `claude plugin list` shows `review-gate@review-gate` as enabled.
2. In a session, `/hooks` lists the `SessionStart`, `UserPromptSubmit`, `PreToolUse` and `Stop` entries from the plugin.
3. In a git repo with a remote, ask Claude to run `git commit --allow-empty -m test` while on `main`. It should be refused with a message about branch → PR.
4. Ask Claude to make a 10-line change to any `.py` or `.ts` file. When it tries to finish, it should start a review.

## Roll it out to a team or a repo

Commit this to the shared repo's **`.claude/settings.json`**:

```json
{
  "extraKnownMarketplaces": {
    "review-gate": {
      "source": { "source": "github", "repo": "obaid/claude-review-gate" }
    }
  },
  "enabledPlugins": {
    "review-gate@review-gate": true
  }
}
```

When a teammate trusts the folder in Claude Code, they are asked to install the marketplace and the plugin. They still need read access to this repo (see Requirements).

If you'd rather every teammate opts in individually, send them the "Install for yourself" steps instead.

## Updating

```
/plugin marketplace update review-gate
```

Then restart Claude Code. To pin a team to a known version, tag releases (`claude plugin tag`) and point the marketplace at a tag or branch.

If you fork this repo and keep the fork private, teammates need read access to it. Background auto-update of a private marketplace also needs a token in the environment, for example `GITHUB_TOKEN`.

## Uninstall

```
/plugin uninstall review-gate@review-gate
/plugin marketplace remove review-gate
```

State and logs stay in `~/.claude/state/review-gate/`. Delete that folder if you want them gone.

## Migrating from a hand-wired hook

If you used `review-gate.py` from `~/.claude/hooks/` before this plugin existed:

1. Remove every hook entry that runs `~/.claude/hooks/review-gate.py` from `~/.claude/settings.json`. There are usually five: `SessionStart`, `UserPromptSubmit`, `PreToolUse` (twice) and `Stop`.
2. Remove the "Code review" section from `~/.claude/CLAUDE.md`. The plugin now supplies the same rules from `RULES.md`.
3. Install the plugin as above and restart.

If you skip step 1, every hook runs twice against the same state files. You'll get two review requests per turn, and the round count races between them.

Your existing state and log in `~/.claude/state/review-gate/` carry over; the plugin uses the same location.
