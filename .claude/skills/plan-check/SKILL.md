---
name: plan-check
description: "Check a proposed design (a set of decisions, a plan section or a ticket) against the project's design rules before any code is written, and turn every gap into a question for the owner. Use when the user types /plan-check, optionally naming what to check."
disable-model-invocation: true
model: sonnet
---

# Plan check

A design is cheapest to fix before the code exists. This checks one design against the project's rules and hands the owner a short list of gaps to settle. It writes no code and edits no document.

## 1. Find the design and the rules

- **The design:** what the user named (a plan section, a file, a ticket, a PR's decisions). If nothing was named, use the decisions agreed in this conversation. If there are none, ask what to check.
- **The rules:** read `CLAUDE.md` fresh. Every rule in it that a design can break applies (skip only how-to sections like commands and doc locations). Rules come from the file, never from memory, so a rule added later is checked automatically.
- **Module rules:** for every module the design touches, Grep its guide (the docs `CLAUDE.md` points to) for limits, rules and "Known limits", and read only those sections, not the whole guide. Rules that belong to one module (limits, priorities, formulas) live there, not in `CLAUDE.md`, and they apply too.
- **The context:** Grep the status document named in `CLAUDE.md` for the design's IDs and read only those lines, for decisions already made. For the code the design calls or replaces, read signatures and docstrings, not whole files. Don't re-open an agreed decision unless the design contradicts it.

Work in this session; don't start subagents.

## 2. Check every rule

For each rule, give one verdict:

- **Meets:** say where the design meets it, concretely (the setting name, the table and columns, the front door).
- **Gap:** the design breaks the rule or leaves room to. Say what would go wrong and when.
- **Not decided:** the design doesn't say yet. Name the decision that's missing.
- **Doesn't apply:** one line saying why.

Be concrete for the rules that are easy to wave through:

- **Settings-driven:** list every number, threshold, time or mode in the design, and the setting each comes from. A value with no setting is a gap unless it's a true constant.
- **Front doors:** name the package's entry point and what callers pass in and get back. Flag any caller that would reach inside another package.
- **ML-ready:** answer all three: which inputs known at decision time are saved (table and columns); how the outcome joins to them (the key); and how who or what decided is recorded (provider, version). A missing answer is a gap.
- **Day trading first:** list anything that differs by holding type and how it's chosen. A hard-coded "day" is a gap.
- **Failure:** for each outside dependency (database, broker, data feed), what happens when it's down at startup and mid-cycle. "Crashes" or "unclear" is a gap.
- **Database:** for each new table or column: the migration, its grants, append-only or not, and which reader-role list it joins.
- **Failure checklist:** for each outside input, loop, alert, time window and open/close state in the design, answer the questions in the "Failure checklist" of `docs/code_style.md`. An unanswered one is a gap.

## 3. Report

Start with a table: one row per rule, the verdict, and a few words of evidence.

Then the gaps and undecided points as questions, at most 3 at a time, each with your recommended answer, worded so "yes" accepts it. Order them so the ones that unblock others come first. After the owner answers, ask the next 3 until none are left.

When everything is settled, list the agreed answers as decisions, ready for the status document. The owner says when to write them there.
