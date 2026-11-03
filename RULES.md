## Code review (every session)

Review is part of the work, not a step at the end. Based on how the Claude Code team reviews code.

- **Verify, don't declare.** Before saying a code change is done, run something that proves it: the build, the tests, a request, a screenshot. Show the result.
- **Fresh-context review.** Review your own diff with fresh eyes before finishing: the `code-review` skill, or a subagent that sees only the diff plus CLAUDE.md/REVIEW.md. Scale it by risk:
  - trivial (a few lines, nothing sensitive): re-read the diff yourself
  - normal: `code-review` at medium
  - sensitive (auth, tokens/secrets, billing, CI workflows, release/updater/installer, migrations, permissions, deploy config) or >400 lines: `code-review` at high plus `security-review`
- **Findings** cite file:line with a concrete failure. No style nits. Mark anything that predates the session as pre-existing. Name the bug's class so every instance gets fixed. End with "Review: N findings, M fixed" or "Review: no issues".
- **Converge.** One review round per turn. After three rounds in a session, review only the new diff, and if the same area keeps failing, re-think the approach with the user instead of patching.
- **Fix it at the source.** When review catches something that should be a standing rule, add one line to the repo's REVIEW.md (or CLAUDE.md, or a lint rule).
- **Every change ships through a PR** in any repo that has a remote: branch (`feature/...` or `fix/...`) → PR → review (Claude's or a human's) → all checks green and review threads resolved → merge to main with `gh pr merge`. Never commit on or push to main directly; the review gate refuses it. If the repo's CI requires a human sign-off label (`human-reviewed`) on sensitive PRs, the user's greenlight in chat ("merge it", "lgtm", "ship it") is that sign-off: add the label, post a PR comment saying they approved it in chat and when, then merge. The hook lets you add it for 15 minutes after such a message, and "wait" or "don't" withdraws it. Never add it without one. The PR body says how it was tested, the risk, and how to revert it. Keep PRs small, one concern each.
- The review-gate plugin's hooks enforce this. The Stop hook asks once per turn when code changed, and skips non-code and tiny low-risk edits. Turn it off per repo with `.claude/review-gate-off`, globally with `~/.claude/state/review-gate/OFF`, or with `CLAUDE_REVIEW_GATE=off`. Its log is at `~/.claude/state/review-gate/log.jsonl`.
