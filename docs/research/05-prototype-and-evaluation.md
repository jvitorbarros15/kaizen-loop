# Open-source prototype and evaluation

For the TypeSafe Jev decision-model architecture and supplied video links, see [Jev and typed decision models](00-jev-decision-models.md).

Build a provider-neutral experiment for ordinary software maintenance tasks with deterministic acceptance tests. Keep the checkout, provider adapter, verifier, lesson store, and context selector as separable components. That makes the learning loop and the model architecture independently testable.

## Prototype stages

1. **Establish traces.** Build one runner for the baseline and add both provider adapters. Each trial gets a fixed base revision, acceptance criteria, independent verifier, maximum attempts and a wall-clock limit. Collect aggregate usage and keep full logs as artifacts.
2. **Add a bounded retry and reviewed memory.** Feed the worker the first actionable failure and relevant source pointers. Distill proposed lessons at the end of completed traces. A lesson carries evidence, scope, version, and expiry or revalidation criteria. Test retrieval against later tasks.
3. **Reduce context deterministically.** Trim repeated tool output, expose line-addressable source, and retrieve only relevant lessons. Add an expansion switch. Benchmark uncached and realistic warm-cache runs as separate profiles.
4. **Compare decision models.** Evaluate Jev, a local typed decision model, and a small generative classifier on the same candidate skills and held-out tasks.
5. **Evaluate the full workflow.** Count selector overhead, fallback calls, worker tokens, and verified solves.

## What to log

| Record | Fields |
| --- | --- |
| Task | ID, base commit, source, task family, verifier version |
| Attempt | Provider and model version, adapter/harness version, seed when available, attempt number, duration, outcome |
| Token and cost breakdown | Fresh input, cache reads and writes when reported, output, reasoning detail when reported, charges, local model time |
| Evidence | Changed paths, test IDs, exact error excerpts, source pointers, artifact identifiers |
| Candidate lesson | Scope, trigger, corrective action, trace ID, evaluation score, review status |
| Sidecar decision | Candidate action IDs, action taken, score or uncertainty, expansion or escalation, observed result |

Use provider totals as the denominator for billing. Where reasoning appears as a subset of output, record it as detail without adding it to the total again. Record unavailable usage fields as unknown. Include failed and retried attempts in the total.

## Comparisons and decision rule

Run paired trials on the same tasks. For each provider, begin with one-shot standard context, then add verifier-backed retries, then reviewed lessons. In a second comparison, keep the same loop and compare context and routing methods. Report pass at the first attempt, pass within budget, tool calls, uncached and cached input separately, output, latency percentiles, dollars per task, and dollars per verified solve. Add a flashback test in which a relevant lesson is updated or withdrawn, and confirm the worker stops retrieving the old revision.

Split by repository or time, deduplicate similar issues, and use unpublished or locally authored acceptance tests where permitted. Keep final tasks and checks outside the optimizer's visible state. Report per-task paired differences and uncertainty intervals, with clustering by repository if multiple tasks share it. Annotate environment failures separately and show whether they remain in the headline denominator. Randomize run order where service load, cache state, or provider drift could affect timing.

A possible starting criterion is a 20% reduction in median total tokens with at most a two-percentage-point quality loss on the held-out set, plus lower cost per verified solve. These are example thresholds and require enough trials to distinguish the proposed margin from noise. Use a paired interval for the success-rate difference and specify the allowed margin before looking at the test results.

## Cost example

If a baseline costs $0.10 per task and solves 70%, it costs about $0.143 per verified solve. If a sidecar variant costs $0.08 per task and solves 68%, it costs about $0.118 per verified solve. The example is illustrative and the quality margin still needs its own check. Add the one-time optimizer or training budget to an amortized cost estimate at the expected run volume. Attribute local inference cost to the same task ledger.

For calibration, first evaluate sidecar scores offline without changing live decisions. Then replay with ranked candidates and abstention. Inspect the trade-off between percentage of calls skipped and errors introduced, especially missed constraints and repeat retries. That curve provides a basis for setting the abstention threshold.

Method references. [Anthropic agent evals](https://www.anthropic.com/research/demystifying-evals-for-ai-agents) · [SWE-bench](https://arxiv.org/abs/2310.06770) · [GEPA](https://arxiv.org/abs/2507.19457) · [SWE-Pruner](https://arxiv.org/abs/2601.16746)
