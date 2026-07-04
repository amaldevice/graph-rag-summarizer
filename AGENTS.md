# AGENTS.md

## Docs

- `docs/todo-in-progress.md` — live onboarding patokan / what's pending
- `docs/completed/completed-tasks.md` — completed archive index and decision history
- `docs/completed/prd/`, `docs/completed/issues/`, `docs/completed/handoffs/` — categorized archive folders

## Agent skills

### Issue tracker

Issues and PRDs for this repo live in GitHub Issues via the `gh` CLI. External PRs are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

This repo uses the default triage labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This repo is single-context: read the root `CONTEXT.md` and `docs/adr/` when present. See `docs/agents/domain.md`.

## Plan Mode

- Make the plan extremely concise. Sacrifice grammar for the sake of concision.
- At the end of each plan, give me a list of unresolved questions to answer, if any.

## Mandatory Progress Tracking

**Every task — big or small — must be tracked in `docs/`.**

### At task start
Update `docs/todo-in-progress.md`:
- Move the task from "Planned / Backlog" to "In Progress"
- Add what's being worked on and why

### At task completion
1. Update `docs/completed/completed-tasks.md` — add what was done, key files changed, verification results
2. Update `docs/todo-in-progress.md` — mark as done, remove from "In Progress"
3. If any new follow-ups were discovered, add them to the backlog

### No exceptions
- Bugfix? Track it.
- Small refactor? Track it.
- Architecture decision? Track it as an ADR entry in `docs/completed/completed-tasks.md`.
- Docs update? Track it.

### Doc naming and archive routing
- Use category prefixes when creating markdown work docs: `prd-...`, `issue-...`, `slice-...`, `handoff-...`.
- While active, keep the work doc in the root `docs/` area that matches the workflow.
- When complete, move the file into the matching archive folder under `docs/completed/` and keep the basename stable.
