#!/usr/bin/env python3
"""Review gate for every Claude Code session.

Modelled on how the Claude Code team reviews code: review is part of the
work, not a gate at the end. When a turn finishes with new code changes, the
Stop hook blocks once and asks Claude to review its own diff with fresh
context, scaled by risk. It never blocks twice in one turn (stop_hook_active),
so author and reviewer cannot cycle forever.

Events (argv[1]):
  session-start  baseline the cwd repo's dirty files, so pre-existing changes
                 are not blamed on this session
  pre-edit       before Edit/Write/MultiEdit/NotebookEdit: baseline the file's
                 repo the first time it is touched; remember non-git files
  stop           decide whether to ask for a review
  prompt         on each user message: a greenlight ("merge it", "lgtm") lets
                 the session add the human-reviewed label for 15 minutes
  pre-bash       before Bash: refuse `git commit` on, or `git push` to, the
                 default branch of a repo that has a remote. Work goes
                 branch -> PR -> review -> checks -> merge.

Only paths, sizes, mtimes and line counts are read. No file contents are
printed or stored.

Turn it off: CLAUDE_REVIEW_GATE=off, a `.claude/review-gate-off` file in the
repo, or ~/.claude/state/review-gate/OFF.
"""

import fnmatch
import hashlib
import json
import os
import subprocess
import sys
import time

STATE_DIR = os.path.expanduser("~/.claude/state/review-gate")
LOG_PATH = os.path.join(STATE_DIR, "log.jsonl")
HOME = os.path.expanduser("~")

CODE_EXTENSIONS = {
    ".swift", ".m", ".mm", ".h", ".c", ".cc", ".cpp", ".hpp",
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte",
    ".go", ".rs", ".rb", ".php", ".java", ".kt", ".kts", ".scala", ".cs",
    ".sh", ".bash", ".zsh", ".sql", ".html", ".css", ".scss",
    ".yml", ".yaml", ".toml", ".xcconfig", ".entitlements", ".plist",
}
CODE_FILENAMES = {"Dockerfile", "Makefile", "Procfile", "Package.swift", "package.json", "composer.json", "wrangler.toml", "wrangler.json", "wrangler.jsonc"}

IGNORED_PARTS = (
    "/build/", "/DerivedData/", "/node_modules/", "/vendor/", "/dist/", "/.next/",
    "/.git/", "/Pods/", "/.build/", "/evals/results/", "/.taste-skill/", "/__pycache__/",
)
IGNORED_PREFIXES = ("/private/tmp/", "/tmp/", os.path.join(HOME, ".claude") + "/")

# Changes here always get the deep review: auth, money, CI, release, installers,
# data migrations, secrets and permissions (the article's "sensitive paths").
RISKY_PATTERNS = (
    "*auth*", "*login*", "*token*", "*secret*", "*credential*", "*keychain*", "*password*",
    "*billing*", "*payment*", "*stripe*", "*subscription*", "*checkout*", "*invoice*",
    "*.github/workflows/*", "*/.circleci/*", "*ci.yml", "*release*", "*sparkle*",
    "*updater*", "*installer*", "*notar*", "*codesign*", "*.entitlements", "*Info.plist",
    "*/migrations/*", "*.env*", "*/config/*", "*permission*", "*sanctum*", "*policy*",
    "*Dockerfile", "*wrangler.*", "*deploy*",
)

TRIVIAL_LINES = 3  # non-risky changes this small skip review
DEEP_LINES = 400   # bigger than this gets the deep review too
CONVERGE_AFTER = 3  # after this many rounds, review only the new diff


def read_input():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def gate_off(repo=None):
    if os.environ.get("CLAUDE_REVIEW_GATE", "").lower() in ("off", "0", "false", "no"):
        return True
    if os.path.exists(os.path.join(STATE_DIR, "OFF")):
        return True
    return bool(repo) and os.path.exists(os.path.join(repo, ".claude", "review-gate-off"))


def state_path(session_id):
    safe = hashlib.sha1((session_id or "unknown").encode()).hexdigest()[:16]
    return os.path.join(STATE_DIR, f"session-{safe}.json")


def load_state(session_id):
    try:
        with open(state_path(session_id)) as f:
            return json.load(f)
    except Exception:
        return {"repos": {}, "loose": {}, "rounds": 0}


def save_state(session_id, state):
    os.makedirs(STATE_DIR, exist_ok=True)
    state["updated"] = time.time()
    tmp = state_path(session_id) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, state_path(session_id))


def git(repo, *args, timeout=10):
    try:
        out = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=timeout)
        return out.stdout if out.returncode == 0 else None
    except Exception:
        return None


def repo_root(path):
    directory = path if os.path.isdir(path) else os.path.dirname(path)
    while directory and not os.path.isdir(directory):
        directory = os.path.dirname(directory)
    if not directory:
        return None
    out = git(directory, "rev-parse", "--show-toplevel", timeout=5)
    return out.strip() if out else None


def file_signature(path):
    try:
        st = os.stat(path)
        return f"{int(st.st_mtime_ns)}:{st.st_size}"
    except FileNotFoundError:
        return "deleted"
    except Exception:
        return "unknown"


def dirty_files(repo):
    """{relative path: signature} for every changed or untracked file."""
    out = git(repo, "status", "--porcelain", "-z", "--untracked-files=all")
    if out is None:
        return None
    files = {}
    entries = out.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        status, rel = entry[:2], entry[3:]
        if status[0] in ("R", "C"):
            i += 1  # skip the rename source
        files[rel] = file_signature(os.path.join(repo, rel))
    return files


def is_code(path, loose=False):
    full = path if path.startswith("/") else "/" + path
    if any(part in full for part in IGNORED_PARTS):
        return False
    if loose and any(full.startswith(prefix) for prefix in IGNORED_PREFIXES):
        return False
    name = os.path.basename(path)
    return name in CODE_FILENAMES or os.path.splitext(name)[1].lower() in CODE_EXTENSIONS


def is_risky(path):
    lowered = "/" + path.lower().lstrip("/")
    return any(fnmatch.fnmatch(lowered, pattern.lower()) for pattern in RISKY_PATTERNS)


MAX_HASHED_LINES = 20000


def line_hashes(path):
    """Multiset of short line hashes, so later edits can be sized without keeping content."""
    counts = {}
    try:
        with open(path, "rb") as f:
            for n, line in enumerate(f):
                if n >= MAX_HASHED_LINES:
                    return None
                h = hashlib.blake2b(line.rstrip(b"\r\n"), digest_size=5).hexdigest()
                counts[h] = counts.get(h, 0) + 1
    except FileNotFoundError:
        return {}
    except Exception:
        return None
    return counts


def lines_since(old, path):
    new = line_hashes(path)
    if old is None or new is None:
        return None
    return sum(abs(new.get(h, 0) - old.get(h, 0)) for h in set(old) | set(new))


def changed_lines(repo, rels):
    total = 0
    tracked = git(repo, "diff", "HEAD", "--numstat", "--", *rels) if rels else ""
    seen = set()
    for line in (tracked or "").splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            seen.add(parts[2])
            if parts[0].isdigit():
                total += int(parts[0]) + int(parts[1])
    for rel in rels:
        if rel in seen:
            continue
        try:  # untracked: count its lines without keeping them
            with open(os.path.join(repo, rel), "rb") as f:
                total += sum(1 for _ in f)
        except Exception:
            pass
    return total


def fingerprints(repo, files):
    return {rel: line_hashes(os.path.join(repo, rel)) for rel in files if is_code(os.path.join(repo, rel))}


def snapshot_repo(state, repo):
    if repo and repo not in state["repos"]:
        files = dirty_files(repo)
        if files is not None:
            state["repos"][repo] = {"reviewed": files, "lines": fingerprints(repo, files)}


def on_session_start(data):
    session_id = data.get("session_id")
    state = load_state(session_id)
    snapshot_repo(state, repo_root(data.get("cwd") or os.getcwd()))
    save_state(session_id, state)


def on_pre_edit(data):
    session_id = data.get("session_id")
    tool_input = data.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not path:
        return
    state = load_state(session_id)
    repo = repo_root(path)
    if repo:
        snapshot_repo(state, repo)
    elif path not in state["loose"]:
        state["loose"][path] = file_signature(path)
    save_state(session_id, state)


def collect_changes(state, cwd):
    """[(repo or None, relative or absolute path)] changed since the last review."""
    cwd_repo = repo_root(cwd)
    if cwd_repo and cwd_repo not in state["repos"]:
        # First sighting at stop (gate installed mid-session): baseline only.
        snapshot_repo(state, cwd_repo)
    changes, current = [], {}
    for repo, info in state["repos"].items():
        if gate_off(repo):
            continue
        now = dirty_files(repo)
        if now is None:
            continue
        current[repo] = now
        for rel, sig in now.items():
            if info["reviewed"].get(rel) != sig and is_code(os.path.join(repo, rel)):
                changes.append((repo, rel))
        # Committed work in a repo whose PRs get a Claude review is reviewed there;
        # reviewing it here too just adds rounds. Elsewhere, committing doesn't skip review.
        pr_reviewed = os.path.exists(os.path.join(repo, ".github", "workflows", "claude-review.yml"))
        for rel in info["reviewed"]:
            if rel not in now and not pr_reviewed and is_code(os.path.join(repo, rel)):
                changes.append((repo, rel))  # committed or reverted since review
    loose_now = {}
    for path, sig in state["loose"].items():
        now_sig = file_signature(path)
        loose_now[path] = now_sig
        if now_sig != sig and is_code(path, loose=True):
            changes.append((None, path))
    return changes, current, loose_now


def mark_reviewed(state, current, loose_now):
    for repo, files in current.items():
        state["repos"][repo]["reviewed"] = files
        state["repos"][repo]["lines"] = fingerprints(repo, files)
    state["loose"].update(loose_now)


def log(event):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass


def on_stop(data):
    session_id = data.get("session_id")
    cwd = data.get("cwd") or os.getcwd()
    state = load_state(session_id)
    changes, current, loose_now = collect_changes(state, cwd)

    if data.get("stop_hook_active"):
        # Claude already ran the review this turn. Accept and move on.
        mark_reviewed(state, current, loose_now)
        save_state(session_id, state)
        return

    if not changes:
        mark_reviewed(state, current, loose_now)
        save_state(session_id, state)
        return

    by_repo = {}
    for repo, path in changes:
        by_repo.setdefault(repo, []).append(path)
    still_present = {
        repo: [p for p in paths if os.path.exists(os.path.join(repo, p) if repo else p)]
        for repo, paths in by_repo.items()
    }
    lines = 0
    for repo, paths in still_present.items():
        known = state["repos"].get(repo, {}).get("lines", {}) if repo else {}
        unknown = []
        for p in paths:
            delta = lines_since(known[p], os.path.join(repo, p)) if p in known else None
            if delta is None:
                unknown.append(p)
            else:
                lines += delta
        lines += changed_lines(repo or "/", unknown)
    risky = sorted({p for _, p in changes if is_risky(p)})

    if not risky and lines <= TRIVIAL_LINES:
        mark_reviewed(state, current, loose_now)
        save_state(session_id, state)
        log({"t": int(time.time()), "session": session_id, "event": "skipped-trivial", "files": len(changes), "lines": lines})
        return

    state["rounds"] = state.get("rounds", 0) + 1
    rounds = state["rounds"]
    tier = "deep" if risky or lines > DEEP_LINES else "standard"
    save_state(session_id, state)
    log({"t": int(time.time()), "session": session_id, "event": "review-requested", "round": rounds,
         "tier": tier, "files": len(changes), "lines": lines, "risky": len(risky),
         "repos": sorted(r for r in by_repo if r)})

    listing = []
    for repo, paths in by_repo.items():
        head = repo or "(outside git)"
        review_md = repo and os.path.exists(os.path.join(repo, "REVIEW.md"))
        listing.append(f"- {head}{'  [has REVIEW.md]' if review_md else ''}")
        listing.extend(f"    {p}" for p in sorted(paths)[:25])
        if len(paths) > 25:
            listing.append(f"    … and {len(paths) - 25} more")

    if tier == "deep":
        how = ("Deep tier"
               + (f" (sensitive paths: {', '.join(risky[:6])})" if risky else f" ({lines} changed lines)")
               + ". Run the code-review skill at level high on these files, and the security-review skill"
               + (" since sensitive paths changed." if risky else " if anything touches input handling, auth or secrets."))
    else:
        how = (f"Standard tier ({lines} changed lines). Run the code-review skill at level medium on these files, "
               "or a fresh-context subagent that sees only the diff, CLAUDE.md and REVIEW.md.")

    converge = ""
    if rounds > CONVERGE_AFTER:
        converge = (f"\nThis is review round {rounds} in this session. Review only what changed since the last round. "
                    "If the same area keeps failing, stop patching and re-evaluate the approach with the user.")

    reason = f"""Review gate: code changed this turn and has not been reviewed yet.

{chr(10).join(listing)}

{how}{converge}

Rules:
1. Read the repo's CLAUDE.md/AGENTS.md and REVIEW.md first; they define what counts as a failure here.
2. Findings need file:line and a concrete failure scenario. No style nits. Mark issues that existed before this session as pre-existing and don't fix them unasked.
3. Name the class of each bug so every instance gets fixed, not just one line.
4. Fix the Important findings, then prove it with something runnable (build, tests, a request, a screenshot). Don't start a second review round in this turn.
5. Finish with a one-line summary: "Review: N findings, M fixed" or "Review: no issues", plus the evidence.
6. If the reviewer flagged something that should be a standing rule, add one line to REVIEW.md (or CLAUDE.md) so it is caught at the source next time.
7. If this change is genuinely trivial or not code (generated files, data, docs), say so in one line and stop."""

    print(json.dumps({"decision": "block", "reason": reason}))


PROTECTED_BRANCHES = {"main", "master"}


def command_repo(command, cwd):
    """Best guess at the repo a shell command acts on: `git -C X`, a leading `cd X`, or cwd."""
    import re
    import shlex
    match = re.search(r"git\s+-C\s+(\"[^\"]+\"|'[^']+'|\S+)", command)
    if match:
        target = shlex.split(match.group(1))[0]
    else:
        match = re.match(r"\s*cd\s+(\"[^\"]+\"|'[^']+'|[^\s;&|]+)", command)
        target = shlex.split(match.group(1))[0] if match else cwd
    target = os.path.expanduser(target)
    if not os.path.isabs(target):
        target = os.path.join(cwd, target)
    return repo_root(target)


def git_segments(command):
    """Each `git ...` invocation in a command line, as a token list without `git` and global options."""
    import re
    import shlex
    segments = []
    for part in re.split(r"&&|\|\||;|\|", command):
        try:
            tokens = shlex.split(part)
        except ValueError:
            tokens = part.split()
        while tokens and "=" in tokens[0] and not tokens[0].startswith("-"):
            tokens = tokens[1:]  # FOO=bar git ...
        if not tokens or os.path.basename(tokens[0]) != "git":
            continue
        tokens = tokens[1:]
        while tokens and tokens[0].startswith("-"):
            flag = tokens.pop(0)
            if flag in ("-C", "-c") and tokens:
                tokens.pop(0)
        segments.append(tokens)
    return segments


APPROVAL_WINDOW_SECONDS = 15 * 60
GREENLIGHT = r"\b(merge|ship it|lgtm|looks good to me|greenlight|green light|approved?)\b"
NOT_YET = r"\b(don'?t|do not|not yet|wait|hold|before you|stop|no)\b"
SIGN_OFF_LABEL = r"\bgh\s+pr\s+edit\b.*--add-label[\s=]+['\"]?human-reviewed"


def approval_path(session_id):
    return state_path(session_id).replace("session-", "approval-")


def on_prompt(data):
    """The user's own message is the only place a sign-off can come from: this
    hook runs on what they type, never on pages, files or tool output."""
    import re
    prompt = (data.get("prompt") or "").lower()
    path = approval_path(data.get("session_id"))
    if re.search(GREENLIGHT, prompt) and not re.search(NOT_YET, prompt):
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(path, "w") as f:
            json.dump({"t": time.time()}, f)
        log({"t": int(time.time()), "session": data.get("session_id"), "event": "greenlight"})
    elif re.search(NOT_YET, prompt) and os.path.exists(path):
        os.remove(path)  # "wait" or "don't merge" withdraws an earlier greenlight


def has_fresh_greenlight(session_id):
    try:
        with open(approval_path(session_id)) as f:
            return time.time() - json.load(f)["t"] < APPROVAL_WINDOW_SECONDS
    except Exception:
        return False


AGENT_FORBIDDEN = (
    # Sign-offs and bypasses are a human's call; agent approvals don't count.
    (SIGN_OFF_LABEL, "Only a human signs off. Ask the user to look at the PR and say so in chat (\"merge it\", \"lgtm\"); then you can add the label."),
    (r"\bgh\s+pr\s+review\b.*(--approve|-a\b)", "Agent approvals don't count as reviews. Ask the user to review."),
    (r"\bgh\s+pr\s+merge\b.*--admin", "Merging with --admin skips the checks and review. Fix what is failing instead."),
    (r"\bgh\s+api\b.*branches/[^\s]+/protection", "Branch protection is changed by the user, not by a session."),
    (r"\bgh\s+api\b.*/rulesets", "Repository rulesets are changed by the user, not by a session."),
)


def on_pre_bash(data):
    command = (data.get("tool_input") or {}).get("command") or ""
    import re
    for pattern, why in AGENT_FORBIDDEN:
        if pattern == SIGN_OFF_LABEL and re.search(pattern, command) and has_fresh_greenlight(data.get("session_id")):
            log({"t": int(time.time()), "session": data.get("session_id"), "event": "sign-off-from-chat"})
            continue
        if re.search(pattern, command):
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                     "permissionDecision": "deny",
                                                     "permissionDecisionReason": why}}))
            log({"t": int(time.time()), "session": data.get("session_id"), "event": "blocked-bypass"})
            return
    if "git" not in command:
        return
    cwd = data.get("cwd") or os.getcwd()
    repo = None
    for tokens in git_segments(command):
        if tokens and tokens[0] in ("checkout", "switch") and ({"-b", "-B", "-c", "-C"} & set(tokens)):
            return  # the command moves to a new branch first
        if not tokens or tokens[0] not in ("commit", "push"):
            continue
        repo = repo or command_repo(command, cwd)
        if not repo or gate_off(repo) or not (git(repo, "remote") or "").strip():
            return  # local-only repos keep committing to main
        branch = (git(repo, "branch", "--show-current") or "").strip()
        verb, args = tokens[0], [t for t in tokens[1:] if not t.startswith("-")]
        if verb == "commit":
            hit = branch in PROTECTED_BRANCHES
        else:
            refspecs = args[1:]
            targets = [r.split(":")[-1].replace("refs/heads/", "").lstrip("+") for r in refspecs] or [branch]
            targets = [branch if t in ("HEAD", "@") else t for t in targets]
            hit = any(t in PROTECTED_BRANCHES for t in targets) or "--mirror" in tokens
        if hit:
            why = (f"`git {verb}` would land on `{branch if verb == 'commit' else 'main'}` directly in {repo}. "
                   "Every change goes branch -> PR -> review -> all checks pass -> merge. "
                   "Create a branch (feature/... or fix/...), commit there, push it, and open a PR with "
                   "`gh pr create` (Testing / Risk / How to revert). Merge with `gh pr merge` once review "
                   "threads are resolved and checks are green.")
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                     "permissionDecision": "deny",
                                                     "permissionDecisionReason": why}}))
            log({"t": int(time.time()), "session": data.get("session_id"), "event": "blocked-main", "verb": verb})
            return


def main():
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    data = read_input()
    if gate_off():
        return
    try:
        if event == "session-start":
            on_session_start(data)
        elif event == "pre-edit":
            on_pre_edit(data)
        elif event == "stop":
            on_stop(data)
        elif event == "pre-bash":
            on_pre_bash(data)
        elif event == "prompt":
            on_prompt(data)
    except Exception as exc:  # never break a session over the gate
        log({"t": int(time.time()), "event": "error", "where": event, "error": type(exc).__name__})


if __name__ == "__main__":
    main()
