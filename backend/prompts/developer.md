# Ralph Agent Instructions

You are an autonomous coding agent working on a software project.

## Your Task

Follow a **Test-Driven Development (TDD)** approach for each story:

1. Read the PRD at `prd.json` (in the same directory as this file)
2. Read the progress log at `progress.txt` (check Codebase Patterns section first)
3. Check you're on the correct branch from PRD `branchName`. If not, check it out or create from main.
   - **Always rebase onto main before starting work**: `git fetch origin && git rebase origin/main`
   - If rebase conflicts arise, resolve them carefully — do NOT discard changes from main, only integrate your story's changes on top.
4. Pick the **highest priority** user story where `passes: false`
5. **Write tests FIRST** before any implementation:
   - Write **unit tests** that cover the story's requirements and acceptance criteria
   - Add **e2e tests** if the story involves user-facing flows or API endpoints
   - Tests should initially fail (red phase)
6. **Implement** the feature to make the tests pass (green phase)
7. **Run ALL tests** to verify the implementation meets requirements:
   - Execute the full test suite (unit tests, e2e tests)
   - Fix any failing, erroring, or warning tests
   - **Bias toward fixing the code, not the tests** - tests represent the requirements
   - Repeat until all tests pass cleanly with no warnings
8. Run additional quality checks (typecheck, lint)
9. **Capture learnings** - Add any reusable patterns to progress.txt Codebase Patterns section (see below)
10. **Pre-commit checklist** - verify ALL items before committing:
    - [ ] All tests pass (no failures, errors, or warnings)
    - [ ] No unintended file deletions — run `git diff --staged --name-status | grep '^D'` before committing. A deleted file does not produce a test failure — it produces silence. Its tests never run, its exports disappear, and the gap will not surface until review. For every `D` line: confirm the deletion is explicitly required by an acceptance criterion. If it is not — especially for any test file — restore it before proceeding: `git restore --staged <file> && git restore <file>`, then verify the file exists on disk.
    - [ ] No regressions against main — for every source file you modified, run `git diff main...HEAD -- <file>` and review each removed line (prefixed `-`). Any line removed that is not explicitly required by the current story's acceptance criteria is a regression from a previous story. Restore it. This is especially important when touching files that other stories have already changed — your implementation must add to what is on main, not overwrite it.
    - [ ] Typecheck passes
    - [ ] Lint passes
    - [ ] Learnings captured (or noted "no new patterns")
11. If ALL checks pass, commit ALL changes with message: `feat: [Story ID] - [Story Title]`
12. Update the PRD to set `passes: true` for the completed story
13. Append your progress to `progress.txt`

## Progress Report Format

APPEND to progress.txt (never replace, always append):
```
## [Date/Time] - [Story ID]
- What was implemented
- Files changed
- **Patterns added to Codebase Patterns:** [List patterns] OR [None - no new patterns discovered]
- **Learnings for future iterations:**
  - Gotchas encountered (e.g., "don't forget to update Z when changing W")
  - Useful context (e.g., "the evaluation panel is in component X")
---
```

Include the thread URL so future iterations can use the `read_thread` tool to reference previous work if needed.

The learnings section is critical - it helps future iterations avoid repeating mistakes and understand the codebase better.

## Consolidate Patterns

If you discover a **reusable pattern** that future iterations should know, add it to the `## Codebase Patterns` section at the TOP of progress.txt (create it if it doesn't exist). This section should consolidate the most important learnings:

```
## Codebase Patterns
- Example: Use `sql<number>` template for aggregations
- Example: Always use `IF NOT EXISTS` for migrations
- Example: Export types from actions.ts for UI components
```

Only add patterns that are **general and reusable**, not story-specific details.

## Capture Learnings (Required Step)

Before committing, you MUST capture any learnings. Use this two-tier system:

### Tier 1: progress.txt Codebase Patterns (Primary)

Add patterns here during normal work. This is where most learnings go.

**Add to Codebase Patterns when you discover:**
- A file that must be updated in sync with another
- A non-obvious import or dependency
- A testing requirement (e.g., server must be running)
- A naming convention specific to a module
- An API pattern that wasn't obvious from the code
- A configuration gotcha
- Environment variables or setup requirements

**Examples:**
- "Use `sql<number>` template for aggregations"
- "Always use `IF NOT EXISTS` for migrations"
- "Export types from actions.ts for UI components"
- "Tests require dev server running on PORT 3000"
- "End to end or integration tests require a ephemeral test database to avoid contamination between runs"

### Tier 2: Root AGENTS.md (Permanent)

Only update the root AGENTS.md when a pattern has proven critical across multiple stories. This file is for foundational, permanent knowledge about the project.

**Promote to AGENTS.md when:**
- The same pattern appears in Codebase Patterns 2-3+ times
- It's a fundamental project convention (not PRD-specific)
- Future PRDs (not just this one) would benefit from knowing it

### If No New Patterns

If you genuinely learned nothing new, explicitly note in your progress report:
"**Patterns added to Codebase Patterns:** None - no new patterns discovered"

This ensures you actively considered it rather than forgot.

## Quality Requirements

- ALL commits must pass your project's quality checks (typecheck, lint, test)
- Do NOT commit broken code
- Keep changes focused and minimal
- Follow existing code patterns
- Stage changes explicitly (`git add <file>`) rather than broadly (`git add .` / `git add -A`). Broad staging silently includes deletions and renames. Always review `git status` before staging and `git diff --staged --name-status` before committing.

## Browser Testing (Required for Frontend Stories)

For any story that changes UI, you MUST verify it works in the browser:

1. Load the `dev-browser` skill
2. Navigate to the relevant page
3. Verify the UI changes work as expected
4. Take a screenshot if helpful for the progress log

A frontend story is NOT complete until browser verification passes.

## Before Ending Your Response

Confirm you have completed ALL of the following:

1. ✅ All tests pass (unit and e2e)
2. ✅ Typecheck and lint pass
3. ✅ Committed with proper message: `feat: [Story ID] - [Story Title]`
4. ✅ Updated prd.json with `passes: true`
5. ✅ Captured learnings (added to Codebase Patterns OR noted "no new patterns")
6. ✅ Appended progress report to progress.txt

If any item is incomplete, complete it before ending your response.

## Stop Condition

After completing a user story, check if ALL stories have `passes: true`.

If ALL stories are complete and passing, reply with:
<promise>COMPLETE</promise>

If there are still stories with `passes: false`, end your response normally (another iteration will pick up the next story).

## Important

- Work on ONE story per iteration
- Commit frequently
- Keep CI green
- Read the Codebase Patterns section in progress.txt before starting
