# Third-party Claude Code tools

Copied into this repo, pinned to a commit, each with its source's LICENSE kept beside it. Every file listed as modified was adapted to this project's rules.

| Tool | Folder | Source | Commit | License | Modified |
|---|---|---|---|---|---|
| grilling | `skills/grilling/` | [mattpocock/skills](https://github.com/mattpocock/skills) | `5863806` | MIT | `SKILL.md`: at most 3 questions per round; facts looked up inline, sub-agent only for broad searches |
| grill-with-docs | `skills/grill-with-docs/` | mattpocock/skills | `5863806` | MIT | no |
| domain-modeling | `skills/domain-modeling/` | mattpocock/skills | `5863806` | MIT | no |
| codebase-design | `skills/codebase-design/` | mattpocock/skills | `5863806` | MIT | `SKILL.md`, `DEEPENING.md`: front door = `__init__.py`; the plan's named seams are real with one adapter; tests-first refactor order, contract tests never deleted |
| improve-codebase-architecture | `skills/improve-codebase-architecture/` | mattpocock/skills | `5863806` | MIT | `SKILL.md`: plan decisions count as ADRs until `docs/adr/` exists |
| tdd | `skills/tdd/` | mattpocock/skills | `5863806` | MIT | `SKILL.md`, `tests.md`: database checks correct for storage and ML records; broker-fake call order is behavior; no `code-review` skill reference; runs for all new code |
| thermo-nuclear-code-quality-review | `skills/thermo-nuclear-code-quality-review/` | [cursor/plugins](https://github.com/cursor/plugins) (`cursor-team-kit`) | `bf0c7cd` | MIT | `SKILL.md`: "Project Rules (Noctis)" section |
| silent-failure-hunter | `agents/silent-failure-hunter.md` | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) (`pr-review-toolkit`) | `b5b01ac` | Apache-2.0 (`agents/LICENSE-pr-review-toolkit`) | project loggers, alerts and error-handling rules; correct patterns listed; runs before a PR, read-only tools |
| pr-test-analyzer | `agents/pr-test-analyzer.md` | anthropics/claude-plugins-official (`pr-review-toolkit`) | `b5b01ac` | Apache-2.0 (`agents/LICENSE-pr-review-toolkit`) | test-gap method and test format from the project docs; trading ratings; runs before a PR, read-only tools |

The Codex-only `agents/openai.yaml` files from mattpocock/skills were left out.

Installed as a plugin, not copied (its license doesn't allow copying): `claude-security@anthropic-plugin-directory` (Anthropic's built-in plugin directory), version 0.11.0, project scope, enabled in `settings.json`. Its scan reports (`CLAUDE-SECURITY-*/`) are git-ignored.
