# YouTube talks and transcript notes

For the TypeSafe Jev decision-model architecture and supplied video links, see [Jev and typed decision models](00-jev-decision-models.md).

Added November 20, 2026. Three talks have timestamped notes based on accessible transcripts. The full transcripts are linked at their sources. Third-party captions can contain recognition errors, especially with product names and command syntax. The additional videos are discovery leads based on publisher descriptions.

## Claude Code team on recurring workflows

Anthropic engineers Thariq Shihipar, Sid Bidasaria, and Robert Boyce describe their own team's practices. Evidence type is a practitioner discussion. [Video](https://www.youtube.com/watch?v=S-sYlFiGFv8) · [Third-party transcript](https://ulisten.ai/channels/claude/how-the-claude-code-team-uses-claude-code_S-sYlFiGFv8/transcript)

| Jump to | Transcript notes |
| --- | --- |
| [8:16](https://www.youtube.com/watch?v=S-sYlFiGFv8&t=496s) | A recurring routine can collect incoming feedback, prioritize it, and act on items it can address confidently. This moves the instruction from the individual task to the recurring process. |
| [9:16](https://www.youtube.com/watch?v=S-sYlFiGFv8&t=556s) | Automated review helps direct human time toward architectural intent and service boundaries. |
| [14:18](https://www.youtube.com/watch?v=S-sYlFiGFv8&t=858s) | The team made its own development environment and end-to-end checks accessible to Claude Tag so it could work on the product itself. |

For the prototype, try a scheduled feedback-to-candidate-lesson run. Measure how often the proposals survive independent verification and human review.

## Thariq Shihipar on planning and running loops in Claude Code

Shihipar walks Peter Yang through workflow design and demonstrates a media-production task. Evidence type is a product demo and interview. [Video](https://www.youtube.com/watch?v=aVO6E181cNU) · [Third-party transcript](https://www.usetranscribe.io/yt/aVO6E181cNU/ai-loops-workflows-cloud)

| Jump to | Transcript notes |
| --- | --- |
| [0:59](https://www.youtube.com/watch?v=aVO6E181cNU&t=59s) | The speaker distinguishes longer-running workflows by how they receive feedback and what ends a run. |
| [5:43](https://www.youtube.com/watch?v=aVO6E181cNU&t=343s) | A concrete completion condition is demonstrated through a rendered video artifact. The result also illustrates that an artifact can exist while details such as names still need checking. |
| [25:26](https://www.youtube.com/watch?v=aVO6E181cNU&t=1526s) | A skill can describe how to set up a workspace. A persistent repository can accumulate reusable scripts and save the agent from rebuilding routine steps. |

For the prototype, define a machine-checkable end state and keep task-specific procedures with the scripts they call. Confirm actual command syntax against the installed version and official docs. [Claude Code documentation](https://code.claude.com/docs/en/overview)

## Ryan Lopopolo on Codex harness engineering

The open conference recording and the timestamped transcript below are the London recording. Evidence type is a firsthand engineering talk. [Video](https://www.youtube.com/watch?v=c8bE0cj7vHY) · [Conference transcript](https://tessl.io/registry/ainativedev/aidevcon-2026-ldn/files/talk-lopopolo-harness-engineering-humans-steer-agents-execute/transcript.md) · [OpenAI case study](https://openai.com/index/harness-engineering/)

| Jump to | Transcript notes |
| --- | --- |
| [8:48](https://www.youtube.com/watch?v=c8bE0cj7vHY&t=528s) | Instructions help when the agent encounters them at the point of decision. Repository navigation and selective context delivery affect whether guidance is followed. |
| [10:12](https://www.youtube.com/watch?v=c8bE0cj7vHY&t=612s) | After a review comment, identify why the agent missed the requirement and decide whether to encode it as documentation, a reviewer criterion, or a test. |
| [12:09](https://www.youtube.com/watch?v=c8bE0cj7vHY&t=729s) | Prompt changes can salvage a single run. Shared documentation, reviewer criteria, and static checks carry the same feedback into future runs. |

For the prototype, label repeated feedback by the enforcement it needs. Measure whether a targeted rule or deterministic test eliminates recurrence, and record any extra context or runtime cost.

## Additional videos

- Neel Rao's Codex talk covers preparing repositories for agent work. Compare with the written case study for primary technical detail. [Video](https://www.youtube.com/watch?v=nD2tRxeSnlI) · [Case study](https://openai.com/index/harness-engineering/)
- OpenAI's engineering-team demo shows the progression from issue to review-ready code. [Video](https://www.youtube.com/watch?v=Ga792ftrBu4)
- The GEPA explainer introduces the underlying prompt-optimization technique. Use the paper for its rollout-budget and benchmark claims. [Video](https://www.youtube.com/watch?v=czy7hvXIImE) · [GEPA paper](https://arxiv.org/abs/2507.19457)
