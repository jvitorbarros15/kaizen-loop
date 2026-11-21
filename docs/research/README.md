# Self-improving agents and token-efficient architectures

Research snapshot for November 20, 2026. JEV refers to the TypeSafe Jev decision model. This is a literature and engineering review, with primary papers, official documentation, author posts, and open-source starting points.

| File | What it answers |
| --- | --- |
| [Six Jev harness patterns](10-six-jev-harness-patterns.md) | Public examples, video timestamps, placement in the loop, and measurements for each pattern |
| [Self-improving agent architecture](08-self-improving-agent-architecture.md) | How execution, learning, and release fit together, with decision contracts, a worked trace, and a local model design |
| [Decision policy and evaluation](09-decision-policy-and-evaluation.md) | How to calibrate routing, enforce guardrails, account for tokens and cost, and test improvements |
| [Jev and typed decision models](00-jev-decision-models.md) | TypeSafe integration, supplied videos, alternatives, and a token-savings experiment |
| [Agent self-improvement](01-self-improvement.md) | What improves, what supplies feedback, and how strong the evidence is |
| [Claude Code](02-claude-code.md) | How to build a bounded loop using Claude Code and the Claude Agent SDK |
| [Codex](03-codex.md) | How to build the same loop using Codex CLI or SDK |
| [Open-source prototype and evaluation](05-prototype-and-evaluation.md) | What to build, what to measure, and which comparisons can settle the question |
| [Annotated sources](06-annotated-sources.md) | Papers, practitioner posts, docs, and open-source projects |
| [YouTube talks and transcript notes](07-youtube-research.md) | Timestamped findings and links to source transcripts |

## Main findings

**Start the decision-model research with Jev.** Compare a typed selector with rules, retrieval, and a cheap generative classifier. [Jev research and architecture](00-jev-decision-models.md)

1. **Start with a verifier-backed loop and versioned lessons.** The highest-leverage feedback for coding is often a reproduction test, a failing assertion, or observable behavior. Persist lessons only after checking that they transfer to a fresh task. Results on intrinsic self-correction make a good case for grounding revisions in external feedback. [Self-correction study](https://arxiv.org/abs/2310.01798) · [Anthropic on agent evals](https://www.anthropic.com/research/demystifying-evals-for-ai-agents)
2. **Measure the effect of context pruning.** SWE-Pruner reports 23–54% token reduction in its agent experiments using a small task-aware line selector. A strong baseline for this project is symbol search plus exact source snippets, compact tool outputs, and a stable cacheable prefix. [SWE-Pruner](https://arxiv.org/abs/2601.16746)
3. **Route bounded decisions through Jev.** Measure whether a typed selector reduces worker calls or the amount of context each worker receives. [Jev decision models](00-jev-decision-models.md)
4. **Optimize cost per verified solve.** Track fresh input, cached input, output and reported reasoning usage, retries, and local inference. A smaller prompt can still lose economically if it breaks cache reuse or increases failures. [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) · [Claude Code costs](https://code.claude.com/docs/en/costs)
