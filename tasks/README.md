# Hackathon task board

The architect/integrator fills [`DEMO_SPEC.md`](DEMO_SPEC.md) and this board on `dev` before parallel implementation starts. Keep task files in this folder and link them here. Assign one owner and allowed paths per task, record dependencies, and put the core demo path first.

| ID | Task | Owner | Status | Depends on |
| --- | --- | --- | --- | --- |

No tasks have been scoped yet. The architect/integrator replaces this line with task rows after the team chooses the demo flow.

## Task file template

Create `T-001-short-name.md` with these headings:

```markdown
# T-001: Task name

Owner: <participant>
Status: todo
Depends on: none

## Outcome
What the user can do.

## Scope and interfaces
Allowed paths, API/data contracts, dependencies, and work excluded from this task. Escalate contract changes to the humans before editing shared schemas.

## Acceptance check
Command or manual steps, with expected result.

## Handoff
Implementation notes, verification result, and known limitations.
```
