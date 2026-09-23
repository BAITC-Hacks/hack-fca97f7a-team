# Project state

Current shared snapshot for the three-person team. Update this file on `dev` when scope, ownership, integration status, or the next action changes. Keep the current facts here; put detailed work in [`tasks/`](tasks/README.md).

## Snapshot

| Item | Current state |
| --- | --- |
| Phase | Preparation; challenge prompt not known yet |
| Demo goal | To be chosen when the prompt arrives |
| Stack and setup command | Not chosen |
| Architect/integrator | Not assigned |
| Participant branches | Not created yet |
| `dev` | Shared workflow and blank demo spec are in place; no product code |
| `main` | Initial repository baseline; no runnable solution yet |
| Latest verification | Documentation checked; application checks do not exist yet |

## Decisions in force

- Three participants each implement on their own branch from `dev`.
- The architect/integrator scopes work in [`tasks/`](tasks/README.md) on `dev` before parallel implementation and publishes a short [`demo spec`](tasks/DEMO_SPEC.md).
- The integrator combines completed work on `dev` and promotes only a verified, runnable demo to `main`.
- Each participant owns one bounded area and directs one coding agent on their own branch. The event requires Codex during development.
- The team will choose packages and a starter template after the challenge and demo flow are known.

## Immediate next actions

1. Read the challenge prompt and choose one demo-worthy user flow.
2. Assign the combined architect/integrator, core agent/backend, and product/UI/demo ownership areas.
3. Choose the stack and have the architect/integrator fill the demo spec, setup and verification commands, and owned task files in `tasks/` on `dev`.
4. Build a runnable input-to-result path with a sample backend response, then create participant branches from the updated `dev` branch.

## Blockers and risks

- The challenge prompt is not available, so product tasks, dependencies, and acceptance checks cannot yet be specified.

## Handoff format for future updates

When this file changes, replace stale snapshot values and record: what is working, the latest verified command and result, what is blocked, who owns the next action, and which `dev` commit contains the current integration. Keep long logs and implementation details in task files or commits.
