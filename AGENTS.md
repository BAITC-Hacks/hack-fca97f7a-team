# Hackalem AI: 5-hour agent workflow

This repository is built by three participants and their agents. Optimize for integration speed and a reliable demo in five hours. Keep decisions and handoffs visible in Git so work can continue without waiting for a meeting.

Before starting work, read `PROJECT_STATE.md`, `tasks/DEMO_SPEC.md`, and your task file. The architect/integrator updates the state after scoping, after each merge, and before release. Keep it current on `dev` so another agent can resume without a verbal handoff.

## Branches and ownership

- `main` is the release branch. It stays at the initial baseline until the first runnable, reviewed demo is ready. Do not commit work in progress directly to `main`.
- `dev` is the shared integration branch. The architect/integrator publishes the plan and merges completed work here.
- Each participant/agent works on a separate branch created from the latest `dev`: `feat/<owner>/<short-task>` (or `fix/<owner>/<short-task>`). Use a separate worktree or clone when agents work concurrently. Never share a checkout between active agents.
- Assign one participant the combined **architect/integrator** role. That person may commit the initial spec and task plan directly to `dev`; implementation still goes through a feature branch. Only this person merges implementation into `dev` and promotes `dev` to `main`.
- Do not force-push shared branches. Keep changes small enough to review and merge throughout the event.

## Three ownership areas

- **Architect/integrator:** owns the tiny shared spec, scaffold, data contracts, shared boundaries, glue code, merges, whole-flow checks, and release. This person also codes.
- **Core agent/backend:** owns the task-specific intelligence behind a small agreed interface, such as `run_agent(input) -> result`. Provide a repeatable example and error behavior.
- **Product/UI/demo:** owns the user journey, interface, API wiring, known-good demo inputs, and presentation. Start with a sample backend response so the UI can be used immediately.

These are ownership areas, not isolated layers. When the challenge has independent user flows, assign each builder a complete flow across UI and server code. Put exact directories and interfaces in the shared spec so agents do not edit the same files by surprise.

Each human directs one coding agent on their own branch and coordinates decisions with the other humans. The [event requires the team to use Codex](https://hackalem.ai/) during development. Avoid an extra hierarchy of planning or coding agents that adds handoffs within this five-hour window.

## First 25 minutes: publish a tiny shared spec

The architect/integrator fills `tasks/DEMO_SPEC.md` and `tasks/README.md`, then creates one Markdown file per task in `tasks/` and commits them to `dev`. Agree together on one 60-second demo story, a small architecture sketch, request/response examples, directory ownership, and concrete acceptance checks. Other agents read the latest `dev` before creating their branches. Do not spend the opening hour on a broad architecture document.

Use `tasks/T-001-short-name.md` names. Each task file should contain:

- **Owner and status:** `todo`, `in progress`, `blocked`, or `done`.
- **Outcome:** what users can do when it is complete.
- **Scope and interfaces:** allowed paths, API/data contract, and dependencies. Do not change a shared contract without telling the other owners.
- **Acceptance check:** a concrete command or manual demo step, with expected result.
- **Handoff:** what changed, how to run it, and any known limitation.

The architect/integrator maintains task scope and ownership on `dev`. Owners update status and handoff in their feature branch; the integrator brings those updates into `dev` with the implementation. If a contract is insufficient, report the gap before redesigning it. The humans agree on the change and update affected task files.

## Build a complete sample path first

Get user input through the UI, API or controller, a sample agent/backend response, and back to a visible result by minute 75 at the latest. The sample may be hardcoded or mocked while the real capability is built. Keep the sample clearly identified so the final demo does not imply a mock is live functionality. Create separate frontend and backend services only when different runtimes or deployment needs require them; agree on request/response examples first.

## Build and integrate

1. The team agrees on the core demo and interfaces. The architect/integrator publishes the spec and tasks on `dev`.
2. The integrator creates the scaffold and a runnable input-to-result path with sample data on a feature branch, then merges it into `dev`.
3. Each owner branches from current `dev`, implements one bounded task within assigned paths, and commits a small, reviewable result. Pull recent `dev` changes regularly.
4. Before handoff, the owner runs the task's acceptance check and records the result in the task file. If the check cannot run, record why and a manual verification step.
5. The integrator reviews and merges one feature branch at a time into `dev` about every 30–45 minutes, resolves conflicts with the owners, and runs the whole flow after each merge. Keep `dev` runnable whenever possible.
6. Promote `dev` to `main` only after the real core flow runs end to end, critical failures are resolved, setup/demo steps are in `README.md`, and the team can reproduce the demo from a fresh checkout. If `dev` is unstable at the deadline, keep the last working release on `main`.

For a conflict or blocker, post the failing command, relevant output, owner, and next decision in the task file. Raise blockers after about 10 minutes rather than silently losing time. Do not add secrets or credentials to Git.

## Demo reliability

Prepare one known-good input and expected result. Cap agent/tool iterations and call time, show useful errors for failed calls, and record enough information to diagnose a failed run. Keep a clearly identified fallback or recording for presentation if a live external dependency fails. Rehearse the full demo at least twice in a row. Do not present sample or cached output as a live agent result.

## Five-hour cadence

| Time from start | Team outcome |
| --- | --- |
| 0–25 min | Choose one demo story, roles, stack, contracts, and file ownership; publish the spec. |
| 25–75 min | Merge a rough end-to-end path into `dev`; owners branch and start bounded work. |
| 75–165 min | Build in parallel; merge small working changes every 30–45 minutes. |
| 165–210 min | Finish integration; avoid major architecture changes. |
| 210–255 min | Stop adding scope; fix reliability, latency, errors, and key UX issues. End feature development by minute 240. |
| 255–280 min | Prepare README, known-good input, demo script, and backup. Rehearse twice, then promote the verified `dev` commit to `main`. |
| 280–300 min | Repeat the demo; fix only demo-breaking issues, then reverify and update the release if needed. |

Prefer a smaller complete flow over several unfinished features. When time runs short, the integrator cuts optional tasks from the release rather than merging unverified work.
