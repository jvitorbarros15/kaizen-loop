# Codex self-improvement loop

Use Codex as a worker with a contract shared by Claude and Codex. The adapter translates CLI or SDK events into an independent result containing run ID, base revision, changes, exit status, usage, and artifact locations. Keep pass/fail and promotion in the controller.

## Codex integration

| Surface | Role |
| --- | --- |
| `AGENTS.md` | Short repository map, test commands and scoped invariants |
| Skills | Procedures invoked for recurring work such as diagnosing a failing test or collecting evidence |
| CLI `codex exec` | Non-interactive runs with JSONL events or schema-constrained final output |
| Codex SDK | Programmatic thread control when a CLI wrapper becomes cumbersome |
| Codex hooks | Available lifecycle integrations for the installed client, with version-specific behavior checked before relying on a particular event |
| OpenAI Responses API | Separate path for a custom harness with explicit API-level context and compaction management |

Official references. [AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md) · [Skills](https://learn.chatgpt.com/docs/build-skills) · [Codex CLI exec](https://learn.chatgpt.com/docs/non-interactive-mode) · [SDK](https://learn.chatgpt.com/docs/codex-sdk) · [Hooks](https://learn.chatgpt.com/docs/hooks) · [API compaction](https://developers.openai.com/api/docs/guides/compaction)

## Example run from a disposable checkout

The controller supplies `task.md` and `result.schema.json`. The prompt should describe the requested result fields as well as the task. Keep generated logs outside the candidate diff, and use a separate path per attempt in the controller.

```powershell
codex exec --sandbox workspace-write --json --output-schema result.schema.json --output-last-message result.json "Read task.md and implement the acceptance criteria. Report changed files, checks run, and blockers." > events.jsonl
```

Check the process exit code, validate the final file, collect usage from the structured event stream where available, and run the controller's checks on the resulting diff. A plausible final JSON result is evidence of what the worker reports. Executed verification supplies the pass signal. Pin the recorded CLI version and capture feature compatibility with `codex exec --help` during adapter setup. [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)

## Where persistent improvement comes from

- **Make repository navigation cheap.** OpenAI's harness engineering case study describes giving Codex a short orientation document backed by repository documentation. For this project, give the worker a succinct map to task fixtures, relevant modules, and verification commands, then fetch exact evidence on demand. [Harness engineering](https://openai.com/index/harness-engineering/)
- **Improve the test and tool interface.** Classify repeated failures. Missing acceptance coverage calls for a stronger fixture. Repeated scavenging for the same files calls for an index or scoped skill. Verbose tool output calls for a parser that preserves exact errors with references to the full log. Compare each change with the previous harness version.
- **Resume strategically.** The CLI documents session resume. Use a recorded session identifier when replaying the same task and context is valuable. Start a separate thread for held-out tasks and for comparisons where earlier task exposure would contaminate the result. [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
- **Audit API and CLI separately.** If the prototype uses the OpenAI API directly, record provider-reported cache hits and compaction behavior. Internal CLI context behavior and usage fields may differ from a hand-built Responses API application. Cache savings depend on reusable prefixes and metering, so compare dollars and context size independently. [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) · [Codex as a platform](https://developers.openai.com/blog/codex-as-a-platform)

Keep a common lesson record, then render short client-specific instructions or skills from reviewed versions. Benchmark within each provider first so a model difference stays separate from any gain due to the loop.
