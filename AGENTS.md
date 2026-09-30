# Agent Instructions

## Handoff Documentation

After completing each implementation stage, update `HANDOFF.md` in the same
change. Keep it concise and use this structure:

```md
# Current Status

## Completed
- ...

## Verification
- Command: ...
- Result: ...

## Known Limitations
- ...

## Next Steps
1. ...
2. ...

## Important Files
- ...
```

The handoff must state the current stage, completed work, changed public
interfaces, exact verification commands and manual scenarios, known
limitations/configuration requirements, the next unfinished stage, and the
important files for the next agent.

Before starting work, read `HANDOFF.md` and
`docs/implementation-plan.md`. Preserve previously confirmed manual scenarios
unless they are re-verified or the change explicitly supersedes them.
