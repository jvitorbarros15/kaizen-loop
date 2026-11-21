# Claude Code self-improvement loop

## Use the right surface for each job

| Surface | Role in the loop |
| --- | --- |
| `CLAUDE.md` and scoped rules | Brief durable project conventions and canonical verification commands |
| Auto memory | Working notes for an individual environment, with an audit before sharing any lesson |
| Skills | Reusable task procedures loaded when relevant, with references kept alongside the skill |
| Hooks | Mechanical checks, event capture, and reduction of verbose outputs |
| `claude -p` or Claude Agent SDK | Worker execution and structured collection of run results |
| External controller | Retry budget, trusted verification, persistent lesson evaluation, and versioning |

Current Claude Code docs also describe conditional `AGENTS.md` support. A shared controller can keep a canonical project guide while testing what each installed client actually loads. The docs distinguish auto memory from project instructions and cover path-specific rules and compaction. [Claude memory](https://code.claude.com/docs/en/memory) · [Skills](https://code.claude.com/docs/en/skills) · [Hooks](https://code.claude.com/docs/en/hooks)

## Example worker contract

From a disposable checkout with standard tool permissions, launch the worker with a concrete output contract. This PowerShell example assumes the task and acceptance criteria are in `task.md`. The controller runs verification independently after the command finishes.

```powershell
claude -p "Read task.md. Implement the smallest change that satisfies its acceptance criteria. Return changed files, checks run, and any unresolved issues." --output-format json
```

For streaming telemetry use the documented stream mode. Parse the result and check the process status. If strong machine-readable final results are needed, apply the documented JSON schema option and validate the resulting payload. Use the SDK when typed events and permission callbacks simplify integration. [Claude non-interactive mode and Agent SDK](https://code.claude.com/docs/en/headless)

## Session and learning design

- **Initialize once.** Record the test command, an explicit acceptance list, and base revision. Seed an immutable task spec and a controller-maintained status file. Anthropic's long-running harness work uses an initializer and incremental sessions to reduce handoff loss. [Effective harnesses](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents)
- **Use fresh sessions for transfer and clean comparisons.** During a retry, resume if preserving tool history is cheaper and important. If the session is cluttered, start fresh with the current diff, the failing test excerpt, and source pointers. Save detailed logs outside the prompt. [Effective context engineering](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents)
- **Keep deterministic work in scripts.** Let a controller or hook parse test output and preserve failed identifiers, expected and actual values, and source locations. Hooks can inject text into context, so keep injected payloads bounded. Keep retry limits and the final pass decision in the controller. [Hook events and output](https://code.claude.com/docs/en/hooks)
- **Treat each lesson as a patch.** For example, after recurring snapshot failures, propose a scoped skill entry that explains when to run the targeted snapshot test, then compare outcomes on later tasks. Put only broadly applicable directives in always-loaded project instructions. [Steering Claude Code](https://claude.com/resources/articles/steering-claude-code-skills-hooks-rules-subagents-and-more)
- **Track usage on every role.** Separate worker, evaluator, summarizer and subagent usage. A separate evaluator can improve independence and context isolation while adding its own prompt and execution cost. Compare the full workflow with direct execution and deterministic checks. [Claude Code costs](https://code.claude.com/docs/en/costs) · [Evaluator and optimizer pattern](https://www.anthropic.com/research/building-effective-agents)

At the Claude API layer, distinguish prompt caching, tool-result clearing, compaction, and cross-session memory. Each addresses a different cost or state problem. Measure end-to-end savings against the standard Claude Code workflow before adopting a custom SDK harness. [Claude Cookbook](https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools)
