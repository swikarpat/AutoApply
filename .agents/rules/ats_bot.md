---
trigger: always_on
---

# ATS Zero-HITL Development Rules

1. **Phased Isolation**: Implement only the active phase requested by the user. Do not scaffold Phase 2+ until Phase 1 tests pass 100%.
2. **Configuration Format**: Always read from `profile.json` using JSON parser. Ensure data adheres strictly to Zod validation schema.
3. **Selector Protocol**:
   - Prefer Playwright accessibility locators (`page.getByRole`, `page.getByLabel`).
   - Never rely on dynamic IDs (e.g., auto-generated alphanumeric IDs like `input-142`).
   - For custom Workday dropdowns, simulate human interaction: Click -> Wait for DOM expansion -> Click Option -> Trigger blur.
4. **Deterministic Gate**: Legal/compliance questions must be resolved through lookup maps against `profile.json`. Never prompt an LLM to guess sponsorship or work status.
5. **Fail-Fast Protocol (No Autonomous Loops)**:
   - Execute test scripts (`npm run ...`) exactly ONCE per user turn.
   - If a test script exits with an error code or logs a failure:
     - DO NOT attempt to rewrite code, patch files, or re-run the command automatically.
     - DO NOT start an autonomous fix-and-retry cycle.
     - Print the exact error log and screenshot location to the terminal and HALT immediately.
     - Wait for explicit user instructions before modifying any files.