# Agent self-improvement loops

A loop can improve the current output, change decisions later in the session, or persist a change that affects future runs. These claims require different tests. Start a new session on a held-out task to measure persistent improvement. Report the initial attempt separately from best-of-N results to expose gains from extra inference.

| Mechanism | State that changes | Feedback | Representative work |
| --- | --- | --- | --- |
| Reason and act | Working context and tool state | Environment observations | [ReAct](https://arxiv.org/abs/2210.03629) |
| Critique and revise | Current answer or patch | Model critique or tool evidence | [Self-Refine](https://arxiv.org/abs/2303.17651) |
| Reflect and remember | Episodic memory | Success, failure, or scalar feedback | [Reflexion](https://arxiv.org/abs/2303.11366) |
| Distill reusable procedures | Insights, workflow or skill library | Successful and failed trajectories | [ExpeL](https://arxiv.org/abs/2308.10144), [Voyager](https://arxiv.org/abs/2305.16291), [AWM](https://arxiv.org/abs/2409.07429) |
| Optimize prompts | Prompts, examples, module instructions | Trace feedback and validation metric | [DSPy](https://arxiv.org/abs/2310.03714), [GEPA](https://arxiv.org/abs/2507.19457) |
| Search over implementations | Harness code, tools, or policy | Executed tasks or structural checks | [ADAS](https://arxiv.org/abs/2408.08435), [DGM](https://arxiv.org/abs/2505.22954), [ELITE](https://arxiv.org/abs/2611.21056) |
| Train model weights | Model policy | Labeled traces or RL rewards | [SCoRe](https://arxiv.org/abs/2409.12917) |

## Evidence and limits

- **Self-critique depends on the task and the signal.** Self-Refine shows gains from iterative feedback across its tasks. Huang et al. find that intrinsic self-correction can degrade reasoning performance in their settings. For software work, pair a revision with an actionable observation such as a failing snapshot, an expected value, or a behavior check. Preserve a passing candidate when the next attempt regresses. [Self-Refine](https://arxiv.org/abs/2303.17651) · [Huang et al.](https://arxiv.org/abs/2310.01798)
- **Memory and skill reuse are different interventions.** Reflexion carries verbal lessons into retries. ExpeL distills insights from experience and retrieves examples. Voyager maintains executable skills in Minecraft. Agent Workflow Memory induces reusable workflows in web-agent settings. These motivate a scoped repository lesson store, with transfer to code maintenance still an empirical question. [Reflexion](https://arxiv.org/abs/2303.11366) · [ExpeL](https://arxiv.org/abs/2308.10144) · [Voyager](https://arxiv.org/abs/2305.16291) · [AWM](https://arxiv.org/abs/2409.07429)
- **Prompt evolution can use richer feedback than a scalar.** GEPA examines trajectories, proposes textual edits, and retains candidates that excel on different examples. The authors report up to 35 times fewer rollouts than GRPO in their six-task comparison. That is an optimization-sample measure. A production prompt can still get longer and cost more per run. Score both quality and cost. [GEPA](https://arxiv.org/abs/2507.19457)
- **Harness evolution is promising and benchmark-sensitive.** SICA reports 17% to 53% on a random subset of SWE-bench Verified. DGM reports 20% to 50% on SWE-bench and 14.2% to 30.7% on Polyglot with an archive of candidate agents. Live-SWE-agent reports 75.4% on SWE-bench Verified with changes during the run. Each uses its own model, task selection, runtime design and budget. [SICA](https://openreview.net/forum?id=rShJCyLsOr) · [DGM](https://arxiv.org/abs/2505.22954) · [Live-SWE-agent](https://arxiv.org/abs/2511.13646)
- **Recent preprint on reducing search cost.** ELITE integrates compatible implementation changes and uses structural validity checks inside the evolution loop. The authors report 60.0% to 85.6% on SWE-bench Pro with no downstream candidate task rollouts guiding evolution, and downstream benchmark evaluation of the resulting systems. Treat the November 2026 result as a preprint and reproduce the comparison before relying on it. [ELITE](https://arxiv.org/abs/2611.21056)

## A loop suitable for both coding agents

1. Open a disposable checkout and load the task, base revision, acceptance criteria, and relevant reviewed lessons.
2. Run one worker attempt. Record a compact trace with file references, diff, exit codes, and summarized tool results.
3. Verify in the controller using a fixed test profile. Classify the outcome as pass, actionable failure, environment failure, or ambiguous.
4. On actionable failure, return the smallest diagnostic that distinguishes the failure and allow a bounded retry. An environment failure goes through a separate recovery budget.
5. Distill a candidate lesson only when evidence suggests reuse. Store its trigger, action, evidence, applicability, and exceptions.
6. Evaluate the lesson against the current baseline across fresh tasks. Promote through a reviewed change when measured quality and cost justify it.

For subjective changes, a rubric-based evaluator can complement tests. Give it the task, artifact, and evidence without the worker's self-assessment. Calibrate against human judgments and retain concrete disagreement examples. Keep the verifier and promotion criteria outside the worker's writable scope. [Anthropic on evals](https://www.anthropic.com/research/demystifying-evals-for-ai-agents) · [Anthropic on harness design](https://www.anthropic.com/research/harness-design-long-running-apps)
