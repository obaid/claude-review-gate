# review-gate

A Claude Code plugin that makes review part of every session instead of a step people forget. It follows how the Claude Code team reviews code.

- **Self-review before a turn ends.** If Claude changed code this turn, the Stop hook blocks once and asks it to review its own diff with fresh context, then fix what it finds and prove the fix (build, tests, a request, a screenshot). The depth scales with risk:
  - **Trivial** (3 lines or fewer, nothing sensitive): skipped.
  - **Standard**: `code-review` at medium, or a fresh-context subagent.
  - **Deep** (more than 400 lines, or a sensitive path such as auth, tokens, billing, CI, release, migrations, permissions or deploy config): `code-review` at high plus `security-review`.
- **It only looks at this session's work.** Files that were already dirty when the session started aren't blamed on it. Non-code files (docs, data) are ignored. It never blocks twice in one turn, so author and reviewer can't loop. After 3 rounds it narrows to the new diff only.
- **PR-only workflow.** In any repo with a remote, `git commit` on `main`/`master` and `git push` to them are refused. Work goes branch → PR → review → green checks → `gh pr merge`.
- **Only a human signs off.** `gh pr merge --admin`, `gh pr review --approve` and edits to branch protection or rulesets are refused. Claude can add the `human-reviewed` label only within 15 minutes of the user typing a greenlight ("merge it", "lgtm", "ship it"). Typing "wait" or "don't" withdraws it.
- **The rules travel with it.** [`RULES.md`](RULES.md) is injected into every session as context, so no one has to edit their CLAUDE.md.

The `code-review` and `security-review` skills it calls ship with Claude Code. Nothing else to install.

## Install

Requires `python3` and `git` (plus `gh` for the PR flow).

```
/plugin marketplace add OWNER/claude-review-gate
/plugin install review-gate@review-gate
```

Restart Claude Code to load the hooks.

**Already running `review-gate.py` from `~/.claude/hooks`?** Remove those hook entries from `~/.claude/settings.json` (and the review section from your CLAUDE.md) first. Otherwise every hook runs twice against the same state.

### Roll it out to a whole repo

Commit this to the repo's `.claude/settings.json`. Anyone who opens the repo in Claude Code is then asked to install the plugin:

```json
{
  "extraKnownMarketplaces": {
    "review-gate": { "source": { "source": "github", "repo": "OWNER/claude-review-gate" } }
  },
  "enabledPlugins": { "review-gate@review-gate": true }
}
```

## Turning it off

| Scope | How |
|---|---|
| One repo | create `.claude/review-gate-off` in the repo |
| Everywhere, for you | `mkdir -p ~/.claude/state/review-gate && touch ~/.claude/state/review-gate/OFF` |
| One session | `CLAUDE_REVIEW_GATE=off claude` |
| Uninstall | `/plugin uninstall review-gate@review-gate` |

## Tuning per repo

Add a `REVIEW.md` at the repo root listing what counts as a failure there (invariants, forbidden patterns, past incidents). The gate tells the reviewer to read it, and asks Claude to add a line to it whenever a review finds something that should be a standing rule.

If a repo's PRs are already reviewed by Claude in CI (`.github/workflows/claude-review.yml`), committed work isn't re-reviewed locally.

The thresholds, sensitive-path patterns and code extensions are constants at the top of [`hooks/review-gate.py`](hooks/review-gate.py).

## Privacy

The hook reads only paths, sizes, mtimes and per-line hashes, to size a diff without keeping any content. State and a log of gate decisions are kept in `~/.claude/state/review-gate/`. Nothing leaves the machine.

## Development

```
python3 tests/test_review_gate.py        # 14 tests; uses a temp HOME and throwaway repos
claude plugin validate .
claude --plugin-dir . plugin details review-gate
```
