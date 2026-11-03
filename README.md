# review-gate

**Claude Code writes the code. review-gate makes it read the code back before it says it's done.**

review-gate is a Claude Code plugin that stops a turn from ending on unreviewed code. When Claude changes code, it has to review its own diff with fresh eyes, fix what it finds, and show that the fix works before it hands control back to you. It also keeps work on branches and pull requests, and leaves the final sign-off to a person.

```
/plugin marketplace add obaid/claude-review-gate
/plugin install review-gate@review-gate
```

Restart Claude Code, and every session from then on is covered.

---

## Why a plugin and not a line in CLAUDE.md

You can tell Claude "always review your changes" in CLAUDE.md. That works until the context gets long, the task gets big, or the turn is nearly over, and then the review is the first thing to slip.

review-gate moves the rule out of the prompt and into **hooks**. Claude Code runs hooks on every event, whatever the model happens to remember:

- **When a turn is about to end**, the gate checks what code changed during it. If real code changed and wasn't reviewed, the turn doesn't end yet. Claude is told what to review and how deeply.
- **Before every shell command**, the gate checks for shortcuts. A commit straight to `main`, an admin merge or an agent approving its own PR is refused before it runs.
- **At session start**, the review rules are loaded into context. Everyone on a team works to the same standard without editing their own CLAUDE.md.

The approach follows how the Claude Code team describes its own review process. Review is part of the work rather than a gate at the end, its depth scales with risk, and every finding comes with a concrete way the code fails.

## What it looks like

An illustrative turn:

```
> add a refund endpoint for orders

⏺ Edited src/orders/refund.ts (+62) and src/orders/refund.test.ts (+22)

  Review gate: code changed this turn and has not been reviewed yet.
    src/orders/refund.ts
    src/orders/refund.test.ts
  Standard tier (84 changed lines). Run the code-review skill at level medium …

⏺ Reviewing the diff with code-review (medium)

  src/orders/refund.ts:41  A second refund for the same order is accepted, so a
  retried request refunds twice. Bug class: missing idempotency check.

⏺ Fixed: refunds are now keyed by order ID. Added a double-refund test.
  npm test → 48 passed

  Review: 1 finding, 1 fixed
```

No one had to ask for that review. On the next turn, only newer changes count.

## How deep the review goes

The gate sizes each turn's changes and picks a tier:

| Change | Review requested |
|---|---|
| 3 lines or fewer, nothing sensitive | none, it's skipped |
| A normal change | `code-review` at medium, or a fresh-context subagent |
| More than 400 lines, **or** any sensitive path (auth, tokens, secrets, billing, payments, CI workflows, releases, installers, migrations, permissions, deploy config) | `code-review` at high **plus** `security-review` |

A few rules keep it from being noisy:

- **Only this session's work counts.** Files that were already modified when the session started aren't blamed on it.
- **Only code counts.** Docs, data and build output are ignored.
- **One review per turn.** The gate never asks twice in a turn, so Claude and its reviewer can't loop. After three rounds in a session, it asks Claude to look only at the newest changes, and to rethink the approach with you if the same area keeps failing.

The `code-review` and `security-review` skills ship with Claude Code. There's nothing else to install.

## Guardrails

In any repo with a git remote, these are refused before they run:

| Command | Why |
|---|---|
| `git commit` on `main` / `master` | Changes go branch → PR → review → green checks → merge |
| `git push` to `main` / `master` | Same |
| `gh pr merge --admin` | Skips the checks and the review |
| `gh pr review --approve` | An agent's approval isn't a review |
| Changes to branch protection or rulesets | Those are yours to change, not a session's |
| Adding the `human-reviewed` label | Allowed only within 15 minutes of *you* typing "lgtm", "ship it" or "merge it". Typing "wait" or "don't" takes it back. |

Repos without a remote, like local scratch projects, can still commit to `main` freely.

## Install

You need Claude Code with plugin support, `python3`, `git`, and `gh` for the PR flow.

**For yourself:**

```
/plugin marketplace add obaid/claude-review-gate
/plugin install review-gate@review-gate
```

**For everyone who works on a repo:** commit this to the repo's `.claude/settings.json`. Teammates are asked to install the plugin when they open the project.

```json
{
  "extraKnownMarketplaces": {
    "review-gate": { "source": { "source": "github", "repo": "obaid/claude-review-gate" } }
  },
  "enabledPlugins": { "review-gate@review-gate": true }
}
```

The [installation guide](docs/INSTALL.md) covers checking it works, updating, uninstalling, and moving off a hand-wired copy of the hook.

## Make it fit your repo

- **Add a `REVIEW.md`** at the repo root listing what counts as a bug in that codebase: "money is integer cents", "every route needs an auth test". The reviewer reads it first. When a review finds something that should be a standing rule, Claude adds a line to it.
- **Switch it off where it doesn't belong.** Use a `.claude/review-gate-off` file for one repo, `CLAUDE_REVIEW_GATE=off` for one session, or `~/.claude/state/review-gate/OFF` for everywhere.
- **Tune the thresholds.** The line limits, sensitive-path patterns and protected branches are constants at the top of [`hooks/review-gate.py`](hooks/review-gate.py).

The [user guide](docs/USER-GUIDE.md) covers all of this in detail: the review tiers, the PR and sign-off flow, writing a good `REVIEW.md`, the decision log and troubleshooting.

## FAQ

**Does it send my code anywhere?**
No. The hook reads file paths, sizes, modification times and per-line hashes, enough to measure a diff without keeping any content. It makes no network calls. Its state and decision log stay in `~/.claude/state/review-gate/`.

**Does it slow Claude down?**
Barely, on turns that don't change code: the hook is a `git status` plus some hashing, milliseconds, with no model call. On turns that do change code, the review takes as long as a review takes. That's the point.

**Can Claude just ignore it?**
The git and `gh` guardrails are hard refusals. The review request is a firm nudge rather than a lock: the turn is held once, and Claude has to respond. If a change really is trivial, or isn't code, Claude can say so in one line and move on.

**Does it need GitHub?**
Reviews work in any repo, and even on files outside git. Only the PR guardrails depend on a remote, and the sign-off label assumes `gh`.

**Does it work on Windows?**
It's tested on macOS and Linux. On Windows, use WSL, or make sure `python3` is on your `PATH`.

## What's in the repo

```
.claude-plugin/   plugin manifest, and a marketplace file so the repo installs directly
hooks/            hooks.json (wiring) and review-gate.py (the gate, standard-library Python)
RULES.md          the review rules loaded into every session
docs/             installation guide and user guide
tests/            end-to-end tests that run the hook against throwaway git repos
```

## Contributing

Issues and pull requests are welcome. Before opening a PR:

```
python3 tests/test_review_gate.py      # runs in a temp HOME; never touches your real state
claude plugin validate .
```

To try a change in a live session without installing it: `claude --plugin-dir /path/to/claude-review-gate`.
