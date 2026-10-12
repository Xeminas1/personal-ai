# XemAi agent teams: scoped roadmap (v0.9.49)

The installed conversation system gains **three roles, not three independent
neural networks or autonomous assistants**. They reuse the existing, bounded,
private specialist inference route, with a maximum of two extra passes under
the present coordinator configuration. The main model remains responsible
for the final answer.

## Conversation roles shipped in v0.9.49

- **Conversation Understanding**: one selective preparatory pass when a
  same-thread follow-up appears to refer to a previous suggestion or correction.
- **Social Intelligence**: one selective preparatory pass for explicit tone
  cues such as frustration and situational sarcasm; it never diagnoses emotion.
- **Conversation Quality Reviewer**: one optional revision pass that
  challenges drift from intent, social context, constraints and appropriate
  reply length. It replaces the ordinary remote reviewer role on selected
  conversational turns; it does **not** stack on top of it.

The preflight roles are mutually exclusive and ordinary factual questions
and simple acknowledgements do not run them. The entire team is disabled in
isolated source analysis, attachments, visual analysis, app self-knowledge,
specific dialogue missions, approved agents, Technology Watch and
research/evidence workflows. Existing latency budgets, worker authentication,
no-tool restrictions, status records and conservative citation checks apply.
If the current worker lacks an updated role or a call fails, the main model
continues without the optional pass.

A local-only laptop may still use its existing optional reviewer with extra
conversation context; no new independent model is installed or downloaded.
The user's feedback is not considered proof of factual correctness.
Real-world improvements remain unproven without comparative evaluation.

## Future agent teams to consider — NOT installed or authorised by this release

1. **Memory & Continuity** — a contextual retriever, chronology checker and
   memory contradiction reviewer. Only persist factual memory through the
   existing owner-controlled evidence and privacy rules.
2. **Software Engineering** — repository mapper, implementation planner,
   test author and bug investigator. Read-only by default; code writes need
   the owner's explicit approval. Useful for XemAi and game modding.
3. **Research & Verification** — source finder, method critic and claim
   verifier. Ensure actual fetched evidence supports citations; not three
   copies of the same model agreeing with itself.
4. **Learning & Benchmarks** — failure-case curator, blind evaluator and
   strategy analyst. Compare baseline and candidate on unseen tasks, retain
   failed examples, and avoid rewarding sycophancy or hallucinations.
5. **Design & Accessibility** — UI inspector, consistency critic and test
   designer for desktop, phone and TV interfaces. Requires real observations,
   not invented screenshots or fabricated user tests.

Prioritise Memory & Continuity and Learning & Benchmarks after observing
conversation-agent performance. Any new team needs separate approval,
latency/compute budgets, clear tools and authority boundaries, and measurable
benefits. No additional teams are created in v0.9.49.
