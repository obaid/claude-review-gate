#!/usr/bin/env python3
"""Drives hooks/review-gate.py the way Claude Code does (event name in argv,
hook JSON on stdin) against throwaway git repos, with HOME pointed at a temp
dir so the real ~/.claude state is never touched.

Run: python3 tests/test_review_gate.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "review-gate.py")


class Gate:
    def __init__(self, home):
        self.env = {**os.environ, "HOME": home, "GIT_CONFIG_GLOBAL": os.devnull}
        self.env.pop("CLAUDE_REVIEW_GATE", None)

    def run(self, event, **payload):
        payload.setdefault("session_id", "test-session")
        out = subprocess.run([sys.executable, HOOK, event], input=json.dumps(payload),
                             capture_output=True, text=True, env=self.env, timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout) if out.stdout.strip() else None


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)


def make_repo(root, remote=True):
    repo = os.path.join(root, "repo")
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", "main")
    with open(os.path.join(repo, "README.md"), "w") as f:
        f.write("hi\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "init")
    if remote:
        git(repo, "remote", "add", "origin", "https://example.com/x.git")
    return repo


def write(path, n_lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("".join(f"x{i} = {i}\n" for i in range(n_lines)))


class ReviewGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)
        self.gate = Gate(self.home)
        self.repo = make_repo(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_session_start_injects_rules(self):
        out = self.gate.run("session-start", cwd=self.repo)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("Verify, don't declare", ctx)

    def test_stop_blocks_once_on_standard_change(self):
        self.gate.run("session-start", cwd=self.repo)
        path = os.path.join(self.repo, "app.py")
        self.gate.run("pre-edit", tool_input={"file_path": path})
        write(path, 20)
        out = self.gate.run("stop", cwd=self.repo)
        self.assertEqual(out["decision"], "block")
        self.assertIn("Standard tier", out["reason"])
        self.assertIn("app.py", out["reason"])
        # Claude reviewed; the second stop in the same turn must let it finish.
        self.assertIsNone(self.gate.run("stop", cwd=self.repo, stop_hook_active=True))
        # Nothing new changed since: next turn is quiet too.
        self.assertIsNone(self.gate.run("stop", cwd=self.repo))

    def test_preexisting_changes_are_not_blamed(self):
        write(os.path.join(self.repo, "old.py"), 50)  # dirty before the session
        self.gate.run("session-start", cwd=self.repo)
        self.assertIsNone(self.gate.run("stop", cwd=self.repo))

    def test_trivial_change_skipped(self):
        self.gate.run("session-start", cwd=self.repo)
        write(os.path.join(self.repo, "tiny.py"), 2)
        self.assertIsNone(self.gate.run("stop", cwd=self.repo))

    def test_non_code_skipped(self):
        self.gate.run("session-start", cwd=self.repo)
        write(os.path.join(self.repo, "notes.md"), 200)
        self.assertIsNone(self.gate.run("stop", cwd=self.repo))

    def test_risky_path_gets_deep_tier(self):
        self.gate.run("session-start", cwd=self.repo)
        write(os.path.join(self.repo, "src", "auth.py"), 2)  # tiny but sensitive
        out = self.gate.run("stop", cwd=self.repo)
        self.assertIn("Deep tier", out["reason"])
        self.assertIn("security-review", out["reason"])

    def test_large_change_gets_deep_tier(self):
        self.gate.run("session-start", cwd=self.repo)
        write(os.path.join(self.repo, "big.py"), 450)
        self.assertIn("Deep tier", self.gate.run("stop", cwd=self.repo)["reason"])

    def test_off_switch_per_repo(self):
        self.gate.run("session-start", cwd=self.repo)
        os.makedirs(os.path.join(self.repo, ".claude"))
        open(os.path.join(self.repo, ".claude", "review-gate-off"), "w").close()
        write(os.path.join(self.repo, "app.py"), 50)
        self.assertIsNone(self.gate.run("stop", cwd=self.repo))

    def deny_reason(self, command, cwd=None):
        out = self.gate.run("pre-bash", cwd=cwd or self.repo, tool_input={"command": command})
        if out is None:
            return None
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        return out["hookSpecificOutput"]["permissionDecisionReason"]

    def test_commit_on_main_refused(self):
        self.assertIn("branch -> PR", self.deny_reason("git commit -m wip"))
        self.assertIn("branch -> PR", self.deny_reason("git push origin main"))
        self.assertIn("branch -> PR", self.deny_reason(f"git -C {self.repo} commit -am x"))

    def test_feature_branch_allowed(self):
        self.assertIsNone(self.deny_reason("git checkout -b feature/x && git commit -m x"))
        git(self.repo, "checkout", "-qb", "fix/y")
        self.assertIsNone(self.deny_reason("git commit -m x && git push -u origin fix/y"))

    def test_local_only_repo_may_commit_to_main(self):
        git(self.repo, "remote", "remove", "origin")
        self.assertIsNone(self.deny_reason("git commit -m x"))

    def test_bypasses_refused(self):
        for cmd in ("gh pr merge 3 --admin", "gh pr review 3 --approve",
                    "gh api repos/o/r/branches/main/protection -X DELETE"):
            self.assertIsNotNone(self.deny_reason(cmd), cmd)

    def test_sign_off_label_needs_chat_greenlight(self):
        label = "gh pr edit 3 --add-label human-reviewed"
        self.assertIsNotNone(self.deny_reason(label))
        self.gate.run("prompt", prompt="looks good, merge it")
        self.assertIsNone(self.deny_reason(label))
        self.gate.run("prompt", prompt="wait, don't merge yet")
        self.assertIsNotNone(self.deny_reason(label))


if __name__ == "__main__":
    unittest.main(verbosity=2)
