# XemAi agent teams — v0.9.50

XemAi now has **five named, on-demand investigation teams**, alongside the
three selectively activated conversational roles released in v0.9.49.
These are **roles/prompts using the existing selected local or hybrid model**,
not separately trained assistants, autonomous processes or background services.

## Explicit team commands

The teams activate only when XemAi receives a direct command naming one:

| Team | Example user message | Three bounded roles |
| --- | --- | --- |
| Memory & Continuity | `Run the memory team to review what we decided about XemAi` | Context Mapper → Timeline Checker → Memory Verifier |
| Software Engineering | `Use the software engineering team to examine the approved project` | Repository Mapper → Change Planner → Test Critic |
| Research & Verification | `Run the research & verification team to assess the supplied studies` | Source Analyst → Methods Critic → Claim Verifier |
| Learning & Benchmarks | `Invoke the learning & benchmarks team to examine our results` | Failure Analyst → Benchmark Planner → Learning Verifier |
| Design & Accessibility | `Run the design and accessibility team to review the XemTV UI` | Interface Observer → Accessibility Critic → Usability Planner |

The existing `Run a self-improvement audit` and `Use agents to investigate...`
commands still use their original supervised workflows. Asking whether an
agent *could* help, or saying "no agents", never runs these teams.

## Evidence and limitations

**Memory:** Only the current user's relevant existing memory excerpts and a
bounded section of the active chat are shared with the explicitly requested
memory team. The team can flag contradictions but cannot alter memories.
Absence of a memory is not proof an earlier event did not happen.

**Engineering:** Analysis is constrained to the existing approved read-only
developer sources and task evidence. The team does not clone other projects,
write patches, compile code or claim to have tested changes.

**Research:** Specialists evaluate retrieved excerpts and source provenance
provided by this turn's existing tools. They must distinguish fetched pages
from snippets and may report that evidence is missing. Valid-looking source
IDs do not establish factual support.

**Learning:** Receives only bounded owner-rating aggregates and an explicit
indication when no verified A/B benchmark has been supplied. Ratings are not
labels for factual correctness; the team cannot train or install models.

**Design:** Can inspect supplied source excerpts and visual reports, when
actually available. It cannot invent pixels, verified colour values,
accessibility audit scores, or unperformed user tests.

All five teams share the existing opt-in three-pass **read-only** operation.
The separate conversation understanding/social/quality specialist roles remain
conditional, budget-limited and do not run automatically for every turn.
The primary model still composes the final answer; agent suggestions are
untrusted model-generated notes, not proof or instructions.

## Safeguards

- No writing, deleting memories, shell commands, installing AI models,
  creating more agents or changing permissions
- Existing read-only tool gateway prevents privileged calls even if an agent
  output requests them
- Runtime capabilities and source files are evidence, not authorisation
- User can disable all named teams using `agent_teams_enabled: false`;
  `agent_team_enabled: false` disables the supervised team route altogether
- Model failures do not become claims of successful investigation
- Existing safeguards for citations and direct human approval still apply

Actual conversational improvement, model parity and end-to-end task quality
require repeated real-model evaluations. Release regression tests check
integration and permissions; they are not evidence of GPT-level reasoning.
