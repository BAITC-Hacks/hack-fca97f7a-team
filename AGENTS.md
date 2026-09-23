# Hackalem AI: 5-hour agent workflow

This repository is built by three participants and their agents. Optimize for a working demo at the end of five hours. Keep decisions and handoffs visible in Git so work can continue without waiting for a meeting.

Before starting work, read `PROJECT_STATE.md` for the latest shared snapshot and `tasks/README.md` for assignments. The architect updates the state after scoping; the integrator updates it after each merge and before release. Keep it current on `dev` so another agent can resume without a verbal handoff.

## Branches and ownership

- `main` is the release branch. It contains only a runnable, reviewed demo. Do not commit work in progress directly to `main`.
- `dev` is the shared integration branch. The architect publishes the task plan here; the integrator merges completed work here.
- Each participant/agent works on a separate branch created from the latest `dev`: `feat/<owner>/<short-task>` (or `fix/<owner>/<short-task>`). Use a separate worktree or clone when agents work concurrently. Never share a checkout between active agents.
- Assign **architect** and **integrator** roles at kickoff. These are roles held by members of the three-person team, not extra participants. All three participants still use their own feature branches for implementation. The architect may commit the initial task plan directly to `dev`; only the integrator merges implementation into `dev` and promotes `dev` to `main`.
- Do not force-push shared branches. Keep changes small enough to review and merge throughout the event.

## Start with a task plan on `dev`

The architect's first deliverable is `tasks/README.md` plus one Markdown file per task in `tasks/`, committed to `dev` before parallel implementation starts. The plan should name the smallest demo-worthy product flow, split work among the three participants, and identify shared interfaces and dependencies. Other agents read the latest `dev` and their task file before creating feature branches.

Use `tasks/T-001-short-name.md` names. Each task file should contain:

- **Owner and status:** `todo`, `in progress`, `blocked`, or `done`.
- **Outcome:** what users can do when it is complete.
- **Scope and interfaces:** expected files or API/data contracts; note dependencies on other tasks.
- **Acceptance check:** a concrete command or manual demo step, with expected result.
- **Handoff:** what changed, how to run it, and any known limitation.

The architect maintains task scope and ownership on `dev`. Owners update their task status and handoff in their feature branch; the integrator brings those updates into `dev` with the implementation. If an interface changes, tell affected owners immediately and update the relevant task files.

## Build and integrate

1. Architect and team agree on the core demo and interfaces. The architect publishes tasks on `dev`.
2. Each owner branches from current `dev`, implements one task, and commits a small, reviewable result. Pull recent `dev` changes regularly.
3. Before handoff, the owner runs the task's acceptance check and records the result in the task file. If the check cannot run, record why and a manual verification step.
4. The integrator reviews and merges one feature branch at a time into `dev`, resolves cross-part conflicts with the owners, and runs a smoke test of the complete flow after each integration. Keep the app runnable on `dev` whenever possible.
5. Promote `dev` to `main` only after the core flow runs end to end, critical failures are resolved, setup/demo steps are in `README.md`, and the team can reproduce the demo from a fresh checkout. If `dev` is unstable at the deadline, keep the last working release on `main`.

For a conflict or blocker, post the failing command, relevant output, owner, and next decision in the task file. Raise blockers after about 10 minutes rather than silently losing time. Do not add secrets or credentials to Git.

## Five-hour cadence

| Time from start | Team outcome |
| --- | --- |
| 0–20 min | Choose one demo flow, assign architect/integrator roles, and choose the stack. |
| 20–40 min | Architect commits scoped tasks and interface contracts to `dev`; owners create branches. |
| 40–210 min | Build in parallel; integrate small working slices into `dev` every 30–45 minutes. |
| 210–270 min | Stop adding scope, connect components, fix critical issues, and rehearse the demo. |
| 270–300 min | Freeze features, verify from a fresh checkout, update `README.md`, and promote the verified `dev` commit to `main`. |

Prefer a smaller complete flow over several unfinished features. When time runs short, the integrator cuts optional tasks from the release rather than merging unverified work.
