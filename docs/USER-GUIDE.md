# User guide

Once review-gate is installed, there's nothing to run. It works through four hook events in every Claude Code session. This guide covers what you'll see, why, and how to steer it.

## What a session looks like

1. **Session start.** The gate records which files in the current repo are already modified, so earlier work isn't blamed on this session. It also loads the review rules from [`RULES.md`](../RULES.md) into Claude's context.
2. **Claude edits code.** The first time Claude touches a file in another repo, or a file outside git, the gate records that file's starting point too.
3. **Claude tries to finish its turn.** If code changed since the last review, the Stop hook pauses it once with a message like this:

   ```
   Review gate: code changed this turn and has not been reviewed yet.

   - /Users/you/src/api  [has REVIEW.md]
       src/orders/refund.ts
       src/orders/refund.test.ts

   Standard tier (84 changed lines). Run the code-review skill at level medium on these files,
   or a fresh-context subagent that sees only the diff, CLAUDE.md and REVIEW.md.

   Rules:
   1. Read the repo's CLAUDE.md/AGENTS.md and REVIEW.md first …
   …
   ```

4. **Claude reviews, fixes and proves the fix.** It runs the review, fixes the important findings, and runs something to show the fix works (tests, a build, a request or a screenshot). It ends with a line such as `Review: 3 findings, 3 fixed`.
5. **Claude finishes.** The gate never pauses twice in one turn. Whatever was reviewed counts as reviewed, and the next turn only looks at newer changes.

You don't need to do anything during this. If you'd rather skip a review for a throwaway change, say so in chat. Claude can answer the gate in one line when a change really is trivial or isn't code.

## Review tiers

| Tier | When | What Claude is asked to run |
|---|---|---|
| **Skipped** | 3 changed lines or fewer, and no sensitive path | nothing |
| **Standard** | everything else | `code-review` at medium, or a fresh-context subagent |
| **Deep** | more than 400 changed lines, **or** any sensitive path | `code-review` at high, plus `security-review` |

**Sensitive paths** match patterns such as `*auth*`, `*token*`, `*secret*`, `*password*`, `*billing*`, `*payment*`, `*stripe*`, `.github/workflows/*`, `*release*`, `*installer*`, `*/migrations/*`, `*.env*`, `*/config/*`, `*permission*`, `*policy*`, `*Dockerfile` and `*deploy*`. A one-line change to `src/auth/session.ts` still gets the deep tier.

**What counts as code:** source files (`.py .ts .tsx .js .go .rs .swift .rb .php .java .kt .cs .sql .sh` and similar), plus `.html .css .yml .yaml .toml .plist` and files such as `Dockerfile`, `Makefile` and `package.json`. Markdown, JSON data, CSVs and images are ignored. So is anything under `node_modules/`, `build/`, `dist/`, `vendor/`, `.next/`, `__pycache__/` and similar. Files outside any git repo are reviewed too, unless they live under `/tmp` or `~/.claude`.

**Many rounds:** after the third review in one session, the gate adds a note asking Claude to review only what changed since the last round. If the same area keeps failing, Claude should stop patching and rethink the approach with you.

## Review findings

The rules ask every review to:

- cite `file:line` with a concrete failure scenario, and leave out style nits;
- mark issues that existed before the session as **pre-existing**, and not fix them unasked;
- name the **class** of each bug (for example "unescaped user input"), so every instance gets fixed, not just one;
- end with `Review: N findings, M fixed` or `Review: no issues`, plus evidence.

## Teach it your repo: `REVIEW.md`

Put a `REVIEW.md` at the root of a repo to tell reviewers what counts as a failure there. The gate's message flags repos that have one, and the reviewer reads it first. Keep it short and concrete:

```markdown
# REVIEW.md

- Money is integer cents everywhere; any float in src/billing is a bug.
- Every new API route needs an auth middleware and a test that calls it unauthenticated.
- Migrations must be reversible; a missing `down` is a blocker.
- Never log request bodies in src/webhooks (they contain card data).
```

When a review catches something that should be a standing rule, Claude is asked to add one line to `REVIEW.md`, or to `CLAUDE.md`, or as a lint rule. That way it's caught at the source next time.

## The PR workflow

In any repo **with a git remote**:

- `git commit` while on `main` or `master` is **refused**.
- `git push` to `main` or `master` (including `HEAD` while on main, and `--mirror`) is **refused**.
- A command that starts with `git checkout -b …` or `git switch -c …` is allowed, because it moves to a new branch first.

Repos with no remote, such as local scratch repos, can commit to main freely.

The expected flow, which Claude follows from the rules:

1. Create a branch: `feature/…` or `fix/…`.
2. Commit, push, and open a PR with `gh pr create`. The PR body says how it was tested, the risk, and how to revert it.
3. Get a review, from Claude or a human.
4. Wait until all checks are green and review threads are resolved.
5. Merge with `gh pr merge`.

Keep PRs small, with one concern each.

## Human sign-off

Some things only a person can do. The gate refuses these when Claude runs them:

| Command | Why |
|---|---|
| `gh pr review --approve` | an agent's approval isn't a review |
| `gh pr merge --admin` | skips the checks and review |
| `gh api …/branches/…/protection` | branch protection is yours to change |
| `gh api …/rulesets` | same |
| `gh pr edit … --add-label human-reviewed` | allowed only after your greenlight (see below) |

**Greenlight from chat.** If your repo's CI requires a `human-reviewed` label on sensitive PRs, you can approve in chat. Type a message containing *merge*, *ship it*, *lgtm*, *looks good to me*, *greenlight* or *approve(d)*. For the next **15 minutes**, Claude may add the label. The rules ask it to also leave a PR comment saying you approved in chat, and when.

A message that also contains *don't*, *do not*, *not yet*, *wait*, *hold*, *before you*, *stop* or *no* does **not** count as a greenlight. Such a message also **withdraws** any earlier greenlight. "lgtm but wait for CI" therefore withdraws approval rather than giving it.

The greenlight only comes from what you type. Text in files, web pages or tool output can't trigger it.

## Turning it off

| Scope | How |
|---|---|
| One repo | create an empty file `.claude/review-gate-off` in the repo (commit it to make it team-wide) |
| Everywhere, for you | `mkdir -p ~/.claude/state/review-gate && touch ~/.claude/state/review-gate/OFF` |
| One session | start Claude Code with `CLAUDE_REVIEW_GATE=off claude` |
| Temporarily | `/plugin disable review-gate@review-gate` |

In a switched-off repo the rules aren't loaded and none of the hooks act. Delete the file, or unset the variable, to turn it back on.

## Tuning

Edit the constants at the top of [`hooks/review-gate.py`](../hooks/review-gate.py) (in a fork, or with a PR to this repo):

| Constant | Default | Meaning |
|---|---|---|
| `TRIVIAL_LINES` | 3 | non-sensitive changes this small are skipped |
| `DEEP_LINES` | 400 | changes bigger than this get the deep tier |
| `CONVERGE_AFTER` | 3 | rounds before the "review only the new diff" note |
| `RISKY_PATTERNS` | see file | paths that always get the deep tier |
| `CODE_EXTENSIONS`, `CODE_FILENAMES` | see file | what counts as code |
| `IGNORED_PARTS` | see file | directories never reviewed |
| `PROTECTED_BRANCHES` | `main`, `master` | branches that refuse direct commits and pushes |
| `APPROVAL_WINDOW_SECONDS` | 900 | how long a chat greenlight lasts |

To change the rules Claude follows, edit [`RULES.md`](../RULES.md).

If a repo already has Claude reviewing its PRs in CI (`.github/workflows/claude-review.yml`), committed work there isn't re-reviewed locally. Uncommitted changes still are.

## Troubleshooting

**Every decision is logged** to `~/.claude/state/review-gate/log.jsonl`, one JSON object per line:

| `event` | Meaning |
|---|---|
| `review-requested` | the Stop hook asked for a review (includes tier, files and line counts) |
| `skipped-trivial` | changes were too small to review |
| `blocked-main` | a commit or push to main was refused |
| `blocked-bypass` | an admin merge, approval or protection change was refused |
| `greenlight` | your message counted as approval |
| `sign-off-from-chat` | the label was added inside the approval window |
| `error` | the hook hit an exception; the session carries on regardless |

```
tail -5 ~/.claude/state/review-gate/log.jsonl
```

| Symptom | Check |
|---|---|
| Never asks for a review | `/hooks` lists the plugin's hooks? `python3 --version` works? An `OFF` file or `CLAUDE_REVIEW_GATE=off` set? Was the change 3 lines or fewer, or not code? |
| Asks twice per turn | The old hand-wired hook is still in `~/.claude/settings.json`. See [Migrating](INSTALL.md#migrating-from-a-hand-wired-hook). |
| Refuses a commit you meant to make | You're on `main` in a repo with a remote. Create a branch first, or add `.claude/review-gate-off` if this repo shouldn't use the PR flow. |
| My greenlight didn't work | The message also contained a "not yet" word such as *no* or *wait*, or more than 15 minutes have passed. Say "lgtm" again. |
| `error` lines in the log | Open an issue with the `where` and `error` fields. |
