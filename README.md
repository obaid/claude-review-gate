# review-gate

**A Claude Code plugin that makes code review part of every session, not a step someone forgets.**

When Claude changes code, it reviews its own diff with fresh eyes before it's allowed to finish the turn, fixes what it finds, and shows proof that the fix works. In any repo with a remote, changes ship through a pull request, never straight to `main`. Only a human signs off.

It follows how the Claude Code team reviews code. It is three small hooks plus a page of rules, with no server, no API keys and nothing leaving your machine.

## Quick start

```
/plugin marketplace add obaid/claude-review-gate
/plugin install review-gate@review-gate
```

Restart Claude Code. That's it. Full steps, the team rollout and troubleshooting are in **[docs/INSTALL.md](docs/INSTALL.md)**.

## What it does

| | |
|---|---|
| 🔍 **Self-review before a turn ends** | If code changed this turn, the Stop hook pauses Claude once and asks for a review scaled to the risk: tiny edits are skipped, normal edits get `code-review` at medium, and sensitive or large edits get `code-review` at high plus `security-review`. |
| 🎯 **Only this session's work** | Files that were already dirty when the session started are not blamed on it. Docs and data files are ignored. It never asks twice in one turn. |
| 🔀 **PR-only workflow** | In repos with a remote, `git commit` on `main`/`master` and `git push` to them are refused. Work goes branch → PR → review → green checks → merge. |
| ✋ **Humans sign off** | Admin merges, agent PR approvals and branch-protection edits are refused. The `human-reviewed` label can only be added right after *you* say "lgtm" or "merge it" in chat. |
| 📜 **Rules come with it** | [`RULES.md`](RULES.md) is loaded into every session, so nobody edits their CLAUDE.md. |

The `code-review` and `security-review` skills it relies on ship with Claude Code.

## Docs

- **[Installation guide](docs/INSTALL.md)**: requirements, installing for yourself, rolling out to a team or repo, verifying, updating, uninstalling, and migrating from a hand-wired hook.
- **[User guide](docs/USER-GUIDE.md)**: what a session looks like, the review tiers, the PR and sign-off flow, writing a `REVIEW.md`, off switches, tuning and troubleshooting.

## Repository layout

```
.claude-plugin/
  plugin.json        plugin manifest
  marketplace.json   lets this repo act as its own plugin marketplace
hooks/
  hooks.json         wires the hook events to review-gate.py
  review-gate.py     the gate (Python 3, standard library only)
RULES.md             review rules, loaded into every session
docs/                installation and user guides
tests/               end-to-end hook tests
```

## Privacy

The hook reads file paths, sizes, modification times and per-line hashes, enough to size a diff without keeping any content. Its state and decision log live in `~/.claude/state/review-gate/`. It makes no network calls.

## Development

```
python3 tests/test_review_gate.py                  # 14 tests; temp HOME, throwaway repos
claude plugin validate .
claude --plugin-dir . plugin details review-gate   # shows the 4 hook events load
```

To try local changes in a session without installing them: `claude --plugin-dir /path/to/claude-review-gate`.
