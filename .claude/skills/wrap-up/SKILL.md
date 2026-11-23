---
name: wrap-up
description: "End-of-session handoff: record where the work stands in the project's status document and in memory so the next chat can pick up without re-deriving anything. Use only when the user types /wrap-up."
disable-model-invocation: true
---

# Wrap-up

Close the session so the next chat starts from an accurate picture. Nothing here writes code or commits.

Two things come from `CLAUDE.md`, so this skill outlives any one plan:

- **Status document:** the file and section named on its **Status** line.
- **Base branch:** the branch PRs target, from its **Workflow** section.

If either is missing, ask the owner rather than guessing.

## 1. Gather the facts

Look these up; don't rely on what you remember from earlier in the chat.

- Current branch, `git status --short`, and the commits on this branch that aren't on the base branch (`git log --oneline <base>..HEAD`).
- PRs merged into the base branch since the status document was last updated: `git log --oneline --merges --first-parent <base>`.
- Test count: `.\venv\Scripts\python.exe -m pytest -q` (last line only). If it fails, report the failures; don't fix them here.
- From this conversation: what was decided, what was built, what's waiting on the owner (a review, a paper run, a commit), and anything left open.

## 2. Update the status document, with the owner's OK

The status document is only edited after the owner confirms. Show the proposed changes as a short before/after, ask once, then apply all of them together.

- **Status section:** replace its dated summary, don't append to it. It holds: today's date, what's done since the last update (with PR numbers), what's in progress and on which branch, what's waiting on the owner, and the next step. Keep it to a few sentences; details belong elsewhere in the document.
- **Status tables:** mark merged work (✅, merge date, PR number) and strike through finished task IDs (`~~EXE-3~~`). Never delete a row.
- **Decisions:** a decision agreed this session that isn't recorded yet goes where the document keeps decisions (or as an ADR, if `CLAUDE.md` says decisions are ADRs), worded as decided, with the date.

Edit with the Edit tool only. After editing a file with non-ASCII characters (`→`, `✅`), search it for `â` or `Ã` to confirm nothing was double-encoded.

## 3. Update memory

Memory doesn't need the owner's OK, but report what changed.

- **Progress memories:** the ones whose descriptions say they track project or tooling progress. Add a dated entry at the top of each one this session touched, absolute dates only: the same facts as the status summary plus anything the next chat needs that the document doesn't hold (who does what next, waiting-on items).
- **`MEMORY.md` index:** update the one-line hook of every memory you changed, so the index never contradicts the file.
- **New preferences or corrections** the owner gave this session: save each as a feedback memory (or update the existing one), with **Why:** and **How to apply:**.
- Before saving, check the fact isn't already recorded; update the existing memory rather than adding a duplicate. Don't save what git or the code already shows.

## 4. Hand off

End with a short message to the owner:

- **Done this session:** a few bullets.
- **Uncommitted changes:** if any, the files, and a suggested one-line past-tense commit message in the repo's style (the owner commits; never commit).
- **Next chat starts with:** the first concrete step, and the opening line to paste (for example "continue the tooling sprint: /plan-check").
- **Open items:** anything waiting on the owner.
