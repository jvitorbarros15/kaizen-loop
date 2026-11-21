# Annotated sources

For the TypeSafe Jev decision-model architecture and supplied video links, see [Jev and typed decision models](00-jev-decision-models.md).

Reviewed for the November 20, 2026 research snapshot. Paper results are author-reported. The links lead to original work, documentation, or implementation repositories. The topic files explain how the results apply to this project.

## Agent loops, memory, and optimization

| Source | What to read it for |
| --- | --- |
| [ReAct](https://arxiv.org/abs/2210.03629) | A baseline for interleaving model decisions with environmental observations. |
| [Self-Refine](https://arxiv.org/abs/2303.17651) | An inference-time generate, critique and revise loop. Compare its setup with external-feedback results. |
| [Large Language Models Cannot Self-Correct Reasoning Yet](https://arxiv.org/abs/2310.01798) | Why intrinsic correction can fail and why evaluation design matters. |
| [Reflexion](https://arxiv.org/abs/2303.11366) | Episodic verbal feedback between attempts. |
| [ExpeL](https://arxiv.org/abs/2308.10144) | Distillation from successful and failed experiences, followed by retrieval. |
| [Voyager](https://arxiv.org/abs/2305.16291) | Executable skill library and environmental validation in Minecraft. |
| [Agent Workflow Memory](https://arxiv.org/abs/2409.07429) | Inducing reusable procedures from web-task trajectories. |
| [DSPy](https://arxiv.org/abs/2310.03714) | Compiling declarative language-model pipelines against a metric. |
| [GEPA](https://arxiv.org/abs/2507.19457) | Reflective prompt evolution, trajectory feedback, and Pareto selection. |
| [ADAS](https://arxiv.org/abs/2408.08435) | Searching over agent programs and evaluating candidate workflows. |
| [SCoRe](https://arxiv.org/abs/2409.12917) | Training a revision policy with reinforcement learning. |
| [SICA](https://openreview.net/forum?id=rShJCyLsOr) | Workshop paper on an agent editing its own harness with cost, speed and quality feedback. |
| [Darwin Gödel Machine](https://arxiv.org/abs/2505.22954) | A population of self-modifying coding agents with empirical selection. |
| [Live-SWE-agent](https://arxiv.org/abs/2511.13646) | Agent evolution during the same task run. |
| [Huxley Gödel Machine](https://arxiv.org/abs/2510.21614) | Budget allocation across evaluation and improvement in a genealogy of candidate agents. |
| [ELITE](https://arxiv.org/abs/2611.21056) | November 2026 preprint on integrating changes without downstream evaluations inside the evolution loop. |
| [AlphaEvolve](https://arxiv.org/abs/2506.13131) | Evolutionary search over executable artifacts against external objectives. Useful for comparison with harness evolution. |
| [Self-Evolving Coding Agents](https://arxiv.org/abs/2608.03392) | 2026 survey and starting point for citation chaining across memory, tools, policies and frameworks. |
| [SWE-bench](https://arxiv.org/abs/2310.06770) | Benchmark construction from GitHub issues and executable tests. |

## Decision models, routing, and context costs

| Source | What to read it for |
| --- | --- |
| [SWE-Pruner](https://arxiv.org/abs/2601.16746) | Task-guided line selection with coding-agent experiments. |
| [LLMLingua-2](https://arxiv.org/abs/2403.12968) | General extractive prompt compression. |
| [RepoCoder](https://arxiv.org/abs/2303.12570) | Iterative retrieval for repository-level completion. Relevant as a retrieval baseline with a different downstream task. |
| [AgentFold](https://arxiv.org/abs/2510.24699) | Proactive context folding in long-horizon web agents. |
| [Scaling Long-Horizon LLM Agent via Context-Folding](https://arxiv.org/abs/2510.11967) | Folding subtask trajectories into summarized state. |
| [FrugalGPT](https://arxiv.org/abs/2305.05176) | Cost-aware model cascades. |
| [RouteLLM](https://arxiv.org/abs/2406.18665) | Routing between models using preference information. |
| [AgentRouter](https://arxiv.org/abs/2609.22951) | Research on routing across steps of agent workflows. |

## Engineering posts and official docs

| Source | Why it matters |
| --- | --- |
| [Anthropic, Building effective agents](https://www.anthropic.com/research/building-effective-agents) | Evaluator–optimizer and other composable patterns. |
| [Anthropic, Effective context engineering](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents) | Compaction, structured notes and selective retrieval. |
| [Anthropic, Effective harnesses for long-running agents](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents) | Initialization, verified increments, and cross-session handoff. |
| [Anthropic, Harness design for long-running apps](https://www.anthropic.com/research/harness-design-long-running-apps) | Separate planning, building, and evaluation roles for long software tasks. |
| [Anthropic, Demystifying evals](https://www.anthropic.com/research/demystifying-evals-for-ai-agents) | Task suites, trials, graders, and evaluating outcomes. |
| [Anthropic, Steering Claude Code](https://claude.com/resources/articles/steering-claude-code-skills-hooks-rules-subagents-and-more) | Practical trade-offs among instructions, skills, hooks, and subagents. |
| [Claude Code docs, programmatic use](https://code.claude.com/docs/en/headless) | CLI and SDK integration. |
| [Claude Code docs, memory](https://code.claude.com/docs/en/memory) | Project rules, instruction discovery, and auto memory. |
| [Claude Code docs, costs](https://code.claude.com/docs/en/costs) | Context usage and role costs. |
| [OpenAI, Harness engineering](https://openai.com/index/harness-engineering/) | Repository organization around agent-legible context and mechanical feedback. |
| [OpenAI, Codex as a platform](https://developers.openai.com/blog/codex-as-a-platform) | The open harness and supported integration surfaces. |
| [OpenAI, non-interactive Codex](https://learn.chatgpt.com/docs/non-interactive-mode) | Structured output and automating CLI runs. |
| [OpenAI, prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) | Stable-prefix economics and usage measurement. |
| [OpenAI, compaction](https://developers.openai.com/api/docs/guides/compaction) | API context management for long runs. |
| [Sakana AI, DGM author post](https://sakana.ai/dgm/) | Accessible account of the archive-based agent search and benchmark results. |
| [Google DeepMind, AlphaEvolve author post](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/) | Candidate programs, executable grading, and application examples. |
| [Geoffrey Huntley, Ralph](https://ghuntley.com/ralph/) | Firsthand practitioner account of a repeated coding loop. Useful for mechanics and workflow inspiration. |

## Open-source starting points

| Repository | Where it fits |
| --- | --- |
| [OpenAI Codex](https://github.com/openai/codex) | Existing worker and CLI implementation. |
| [Anthropic long-running agents example](https://github.com/anthropics/cwc-long-running-agents) | Claude Code and SDK reference patterns for checkpoints and evaluation. |
| [DSPy](https://github.com/stanfordnlp/dspy) | Prompt and pipeline optimization framework. |
| [GEPA](https://github.com/gepa-ai/gepa) | Reflective optimization implementation. |
| [DGM](https://github.com/jennyzzt/dgm) | Experimental self-modifying agent harness. |
| [SWE-Pruner](https://github.com/Ayanami1314/swe-pruner) | Learned coding-context compression comparison. |

The review prioritized primary sources, direct relevance to coding-agent workflows, documented platform interfaces, and papers with measurable comparisons. Benchmark numbers describe the cited experiments. The proposed coding sidecar, evaluation thresholds, and rollout stages are design hypotheses for this workspace.
