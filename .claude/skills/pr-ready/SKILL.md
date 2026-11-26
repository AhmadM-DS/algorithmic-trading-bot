---
name: pr-ready
description: "Pre-PR checklist: run the tests and secret scan, send the branch to the right reviewers, check the docs and decisions that no tool checks, and hand back one ranked list plus a PR description. Use when the user types /pr-ready (add 'quick' to skip the reviewer agents)."
disable-model-invocation: true
---

# PR ready

Answer one question before the owner opens a PR: is this branch ready? Check everything, change nothing, and hand back one ranked list. The owner decides what to fix, commits, and opens the PR.

Read `CLAUDE.md` fresh first: the base branch (Workflow), the test and scan commands (Commands), and where docs live (Docs). Use those, not names remembered from earlier.

## 1. What's on the branch

- If the current branch is the base branch, stop: there's nothing to review.
- List the changes: `git diff --stat <base>...HEAD` for commits, plus `git status --short` for uncommitted work. Review both; the owner may not have committed yet.
- Sort the changed files into: code (`src/`), tests, SQL, Claude tooling (`.claude/`), docs, other. The sort decides which checks below apply.

## 2. Mechanical checks

Run these first; they're cheap and a failure here is a blocker.

- **Tests:** the full suite, with the command in `CLAUDE.md`. Report the count. A failure is a blocker; list each failing test, don't fix it here.
- **Secrets in the branch's commits:** `gitleaks git --redact --log-opts="<base>..HEAD"`. Uncommitted changes are scanned by the commit hook when the owner commits.
- **Claude tooling:** if anything under `.claude/` changed, validate it with `claude plugin validate .claude`. In the VS Code extension, `claude` isn't on PATH; use the binary bundled in the extension (`resources/native-binary/claude.exe`). A failed validation means a skill or agent silently doesn't load.
- **Database:** for a new migration, check it's in the integration build list and that the reader-permission guard tests ran and passed.
- **Failure checklist:** check every new or changed function in `src/` against the "Failure checklist" in `docs/code_style.md` yourself (no agent); each miss is a finding. In step 3, tell each reviewer to check against it too.

If CI already runs one of these checks for the branch, skip it and say so.

## 3. Reviewers

Skip this step if the owner typed `quick`. Otherwise launch the reviewers that apply, in parallel, each on this branch's diff against the base branch including uncommitted changes. They're review-only.

| Reviewer | Run when |
|---|---|
| `trading-safety-reviewer` agent | `src/` or SQL changed |
| `silent-failure-hunter` agent | `src/` changed |
| `pr-test-analyzer` agent | `src/` or tests changed |
| `code-review` skill, at medium | any code changed (bugs) |

Tell the owner the cost: each agent reads the code on its own (tens of thousands of tokens each).

Two reviews this skill can't run itself; recommend them when they apply:

- `/thermo-nuclear-code-quality-review` (structure): when the branch adds a package, a file grows past a few hundred lines, or the diff is large. The owner types it.
- The `claude-security` scan: only before merging the base branch into `main`, not for PRs into the base branch.

## 4. Docs and decisions

No tool checks these, so check each one:

- **Module guides:** every module whose behavior changed has its guide (from the Docs section of `CLAUDE.md`) updated to match. Name the guide and the section that's stale.
- **Protection map:** if a path to the broker or the trade tables, or a protection, was added or changed, the map is updated (the trading-safety reviewer also checks this).
- **Status document:** the tasks this branch finishes are ready to strike through, and decisions made while building it are recorded where `CLAUDE.md` says decisions live. Propose the edits; the owner approves them.
- **Standing rules:** if the branch introduced a rule every session should know, propose the line for `CLAUDE.md`.
- **Style:** new and changed lines follow the style guide; don't flag untouched code.

## 5. Report

- **Checklist table:** each check from steps 2-4, with pass, fail, skipped (and why) or not applicable.
- **Findings:** from every reviewer and check, merged, with duplicates combined (keep the clearest explanation and note which reviewers agreed), ranked: blockers first (failing tests, secrets, trading-safety BLOCKERs, bugs that place, size or close a trade wrongly), then high, then the rest. Each with file and line, what goes wrong, and the suggested fix.
- **Verdict:** ready, ready after the listed fixes, or not ready.
- **For the PR:** if there's uncommitted work, a one-line past-tense commit message in the repo's style. Then a PR title and a short description (what changed, why, how it was tested), and the `gh` commands from the owner's workflow with the base branch filled in.

Then ask which findings to fix. Fixes follow the tests-first rule. Never commit, push or open the PR.
