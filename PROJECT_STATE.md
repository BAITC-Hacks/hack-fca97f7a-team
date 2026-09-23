# Project state

Current shared snapshot for the three-person team. Update this file on `dev` when scope, ownership, integration status, or the next action changes. Keep the current facts here; put detailed work in [`tasks/`](tasks/README.md).

## Snapshot

| Item | Current state |
| --- | --- |
| Phase | Preparation; challenge prompt not known yet |
| Demo goal | To be chosen when the prompt arrives |
| Stack and setup command | Not chosen |
| Architect | Not assigned |
| Integrator | Not assigned |
| Participant branches | Not created yet |
| `dev` | Shared workflow and task board are in place; no product code |
| `main` | Initial repository baseline; no runnable solution yet |
| Latest verification | Documentation checked; application checks do not exist yet |

## Decisions in force

- Three participants each implement on their own branch from `dev`.
- The architect scopes work in [`tasks/`](tasks/README.md) on `dev` before parallel implementation.
- The integrator combines completed work on `dev` and promotes only a verified, runnable demo to `main`.
- The team will choose packages and a starter template after the challenge and demo flow are known.

## Immediate next actions

1. Read the challenge prompt and choose one demo-worthy user flow.
2. Assign architect and integrator roles among the three participants.
3. Choose the stack, record setup and verification commands, and have the architect create owned task files in `tasks/` on `dev`.
4. Create participant branches from the updated `dev` branch and start the first working slice.

## Blockers and risks

- The challenge prompt is not available, so product tasks, dependencies, and acceptance checks cannot yet be specified.

## Handoff format for future updates

When this file changes, replace stale snapshot values and record: what is working, the latest verified command and result, what is blocked, who owns the next action, and which `dev` commit contains the current integration. Keep long logs and implementation details in task files or commits.
