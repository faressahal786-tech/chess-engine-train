# AGENTS.md

## Autonomous Maintenance Protocol
When instructed to run maintenance, follow these exact steps sequentially:

1. **Bug Scanning**: Analyze modified and recently touched files for bugs, edge cases, memory leaks, or unhandled errors.
2. **Performance Optimization**: Identify slow algorithms, redundant operations, or unneeded database/API calls. Refactor the code to run faster and execute more efficiently.
3. **Verification**: Run the test suite (`npm test`, `pytest`, etc.) or linter to ensure no breaking changes were introduced.
4. **Git Operations**:
   - If improvements or fixes were made, commit them with a concise, clear message.
   - Run `git push` to upload changes to the remote branch.
   - If no actionable bugs or speed optimizations were found, do NOT create empty commits or push anything.