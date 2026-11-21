# TypeSafe Jev and decision models for agent harnesses

Research update for November 20, 2026. Jev means TypeSafe's typed decision model. This is the primary architecture track for reducing Claude and Codex usage. [TypeSafe's coding-agent guide](https://docs.typesafe.ai/introduction/coding-agents)

## What Jev does and where it fits

Jev takes a state and one or more typed questions. A Choice returns a selection and per-option probabilities, a Score evaluates a rubric, and a Noul returns a 0–1 value for a proposition. Call it from the orchestration layer, where the choices are predefined and software owns the next step. Claude Code and Codex remain the workers for investigation, planning, patch generation and ambiguous cases. The TypeSafe agent skill teaches a coding agent to build an integration. Runtime savings require the application or outer controller to execute that integration. [System One](https://docs.typesafe.ai/concepts/system-one) · [Coding-agent guide](https://docs.typesafe.ai/introduction/coding-agents)

```text
task or observed result
  -> deterministic handling for known cases
  -> typed decision on compact state for ambiguous, bounded cases
      -> load selected skill or evidence
      -> invoke Claude or Codex when the task needs generation or review
      -> abstain and expand context when the answer is unclear
  -> execute the approved action and verify the observed outcome
```

**First experiment.** Put a skill selector in front of both provider adapters. Ask for a choice among a short list of skill descriptions plus “none.” Retrieve the selected skill body only after the decision. Compare exact path and keyword rules, embedding retrieval, Jev, and a small local model. The same outer controller can later select focused test profiles or rank retrieved evidence. A selector that runs as a tool inside an existing Claude or Codex turn may reduce later context or calls. A selector before the worker can avoid launching a worker at all when the remaining action is mechanical. [Probability routing](https://docs.typesafe.ai/patterns/probability-routing) · [Noul screening](https://docs.typesafe.ai/patterns/noul-screen)

**Self-improvement.** Record the decision, candidate set, confidence, fallback, and independently verified outcome. Use those records to improve descriptions, thresholds, routing policy, and eventually an open decision model. Train and calibrate on prior tasks and test on later repositories or task families. Preserve test results as acceptance evidence. The decision model's score can prioritize review.

## The two supplied videos

- **Sam Witteveen, Using Jev In Your Agent Harness.** The video and mirrored chapter metadata identify a progression from reducing full LLM calls to wiring Jev into a harness, followed by progressive skill disclosure and retrieval reranking demos. Jump to [2:35, full-call cost](https://www.youtube.com/watch?v=zaLQ0AnY9dI&t=155s), [7:41, wiring](https://www.youtube.com/watch?v=zaLQ0AnY9dI&t=461s), [8:35, Jev runs the loop](https://www.youtube.com/watch?v=zaLQ0AnY9dI&t=515s), [12:19, skill demo](https://www.youtube.com/watch?v=zaLQ0AnY9dI&t=739s), and [16:33, reranking demo](https://www.youtube.com/watch?v=zaLQ0AnY9dI&t=993s). These notes use chapter metadata and a publisher-description mirror. No transcript was retrieved. The demo description links Eikos-27B, which is a separate open-weight candidate. [Original video](https://youtu.be/zaLQ0AnY9dI) · [Chapter metadata](https://natokhd.com/video/using-jev-in-your-agent-harness/zaLQ0AnY9dI) · [Eikos model card](https://huggingface.co/caiovicentino1/Eikos-27B)
- **Video ID L2K__oshGds.** The supplied short URL, canonical URL, metadata endpoint, and exact-ID searches did not provide a verifiable title, chapters, or transcript. The link remains in the source list for follow-up. [Supplied video](https://youtu.be/L2K__oshGds)

## Alternatives from the screenshot

Decision Index 0.4.1 scores below are from its text leaderboard snapshot. Artificial Analysis has its own methodology and currently labels its live board v2.1. JevBench is a third benchmark. Record benchmark edition, model snapshot, execution mode, and hardware before comparing apparent winners. [Decision Index dataset](https://huggingface.co/datasets/multimodalart/decision-index-leaderboard) · [Artificial Analysis methodology](https://artificialanalysis.ai/methodology/decision-index) · [Artificial Analysis v2.1](https://artificialanalysis.ai/evaluations/artificial-analysis-decision-index)

| Candidate | What the cited sources establish | Experiment role |
| --- | --- | --- |
| TypeSafe Jev 1.14 | 60.24 in the Decision Index snapshot. Hosted typed API. [Leaderboard](https://huggingface.co/datasets/multimodalart/decision-index-leaderboard) | Reference integration and calibration baseline |
| Karpo Decision 31B | 73.86, rank 1, with 94.3 ms median listed for the submitted run. That latency is specific to the test setup. [Leaderboard](https://huggingface.co/datasets/multimodalart/decision-index-leaderboard) · [Publisher](https://karpo.ai/blog/karpo-decision-31b) | Higher-capacity open-weight comparator |
| Fastino GLiDE 27B | 73.37 for glide-v1.2.1-loop, rank 2. Review the model-card license before commercialization. [Leaderboard](https://huggingface.co/datasets/multimodalart/decision-index-leaderboard) · [Model card](https://huggingface.co/fastino/GLiDE-27B) | Higher-capacity comparator with version and license tracking |
| vLLM-SR d3-ultra and d3-flash | 70.18 for d3-ultra, rank 14. The screenshot groups two variants. The listed score belongs to ultra. [Leaderboard](https://huggingface.co/datasets/multimodalart/decision-index-leaderboard) · [Ultra model card](https://huggingface.co/vllm-sr/d3-ultra) | Compare the smaller variant when local serving matters |
| Mammoth-1 and Elephant-1 | 68.44 for Mammoth-1 in the official dataset. Treat the screenshot's other scores as leads until matched to the exact model and benchmark release. [Leaderboard](https://huggingface.co/datasets/multimodalart/decision-index-leaderboard) · [Mammoth model card](https://huggingface.co/baselabs/mammoth-1) | Mammoth as a candidate for accuracy comparison |
| Perplexity Decider v1.3 | 67.67 for the 27B version. The leaderboard row says weights are forthcoming and has no checkpoint URL. A prior version has a published model card. [Leaderboard](https://huggingface.co/datasets/multimodalart/decision-index-leaderboard) · [v1.2 model card](https://huggingface.co/perplexity-ai/pplx-decider-v1.2) | Confirm availability of the exact release before selecting it |
| Cygnet and Winnow 12B | Both have public project artifacts. The claimed JevBench 1.5.4 statistical tie remains unverified here. [Cygnet recipe](https://github.com/blockbrain-ai/cygnet-recipe) · [Winnow benchmarks](https://huggingface.co/EldanRing/Winnow-12B/blob/main/docs/BENCHMARKS.md) | Candidate local models to compare on task-specific data |
| Kev and Cloudflare Clef | Kev 27B has a model card. Cloudflare publishes Clef and Clef-flash as open decision models. [Kev model card](https://huggingface.co/jaredpalmer/kev-27b) · [Cloudflare release](https://blog.cloudflare.com/clef-decision-models/) | Start with Clef-flash or a verified small Kev variant when testing local overhead |

The screenshot's license labels and hardware claims are leads. For weights that will ship, read the exact checkpoint license and the base-model terms. For local serving, measure peak memory with the intended quantization, context and concurrency. Dry weights alone omit runtime memory.

## Model architecture and evidence

Jev exposes a decision contract. Its internal architecture is unpublished in the cited controlled study. An open implementation can reuse a text backbone with an option-scoring readout, calibrate probabilities on held-out data, and expose the same typed interface to the harness. Several leaderboard entries are explicitly labeled autoregressive, so verify whether the endpoint scores options directly or generates an output internally. TypeSafe's open Python adapter supplies a generative API comparison using a compatible client interface. [Small Heads, Strong Decisions](https://arxiv.org/abs/2611.15592) · [TypeSafe Python adapter](https://github.com/typesafe-ai/system-one-adapter-python)

The controlled readout study found similar in-domain accuracy across five small-model readouts. Its simpler cosine head had lower inference time than a more complex comparison in that setup. A separate November preprint found strong results for some decision judges, including in settings where a reference answer is reused across candidates, with substantial variation between models under adversarial inputs. Both are reasons to test model and threshold choices on this harness's data. [Controlled readout study](https://arxiv.org/abs/2611.15592) · [Decision judge comparison](https://arxiv.org/abs/2611.00505)

## How to prove the savings

Freeze the workers, tasks, and acceptance tests. Compare the original route, rules and retrieval, an inexpensive generative classifier with typed output, hosted Jev, and a locally served decision model. Log decisions, calibration, coverage at each confidence threshold, false skips, paid worker calls, input/output and cached usage, router cost, retries, and p50/p95 latency. Include the time and cost of serial router calls that fail or escalate. For high-impact decisions keep deterministic permission checks and explicit fallbacks in the controller.

Estimate break-even per original opportunity as the **verified net value of avoided worker calls and prompt tokens**, minus **decision cost and added retry or escalation cost**. Score final pass rate and cost per verified solve together. A decision inserted as an extra round trip can lose even with short or zero generated text. A selector that avoids loading several skills or skips an entire model call is much more likely to pay for itself. [General prototype and evaluation plan](05-prototype-and-evaluation.md)
