# XemAi conversational intelligence: evaluation (draft)

This is a **candidate**, not a release or evidence that XemAi has GPT-level
conversational understanding. Strong conversational ability depends on both
the underlying language model and the surrounding conversation software.

## Scope

The `app/conversation_skills.py` coach reminds the model to resolve references
to recent turns, infer the user's conversational purpose, respond naturally to
corrections and appreciation, and avoid repeating generic model disclaimers.
It never embeds raw user or assistant text in system instructions.

The GUI/mobile app enables this cue only for ordinary multi-turn dialogue.
It is excluded from separate source/attachment, vision, special-agent, named
dialogue, app-inventory, saved-watch and research paths to protect their
existing grounding and execution controls. First-turn chats remain unchanged
apart from the general social rules in the ordinary system prompt.

## Test on an existing local Ollama installation

From the repository directory:

```powershell
python test_conversation_skills.py
python conversation_intelligence_benchmark.py --dry-run
python conversation_intelligence_benchmark.py --model qwen3:8b --without-coach --output baseline-no-coach.json
python conversation_intelligence_benchmark.py --model qwen3:8b --output coached.json
```

`--without-coach` disables **only the new turn-level instruction**, not the
general social-style changes in `app/prompts.py`. It therefore establishes
an A/B test of the turn coach *within this candidate branch*, rather than an
unaltered v0.9.47 baseline. Comparing the full update to v0.9.47 requires
running the same fixed questions against the independently checked-out
v0.9.47 application with its original prompt/route.

Run against any other *already installed and explicitly selected* Ollama
model with `--model MODEL_NAME`. Neither this harness nor XemAi installs
models or modifies inference weights. All examples are synthetic and contain
no owner chat history. Generated answers can be saved to an explicitly
specified local JSON file; there is no automatic upload.

## Human review

Review model identity, answer and criterion for each of the twelve scenarios.
Randomise the variant labels when comparing answers. Score the following
separately on a consistent 0–5 scale:

1. **Intent:** Did the answer respond to the implied request and preserve
   the right subject, without conflating the user with the assistant?
2. **Continuity:** Did it resolve pronouns and short corrections against
   visible preceding turns and respect changing requirements?
3. **Social judgement:** Was the reply proportionate, tactful and natural,
   without flattery, defensiveness or inappropriate invented feelings?
4. **Calibration:** Did it avoid false memories, unsupported capabilities,
   fabricated citations, and unwarranted confidence?
5. **Agency:** Did it avoid treating a conversational agreement as consent
   for consequential operations?

Also record latency, empty answers, failed generations, tool mistakes and
model misidentification. Correctness and policy/permission regressions should
block rollout even if the mean tone score increases.

Twelve synthetic scenarios are just a smoke test: use fresh held-out,
human-written prompts, longer conversations, unseen wording, and real
consented user interactions for a credible quality estimate. A comparator
(e.g. a GPT response) is a reference point, not an automatic truth label.
Keep the evaluation blind where possible, repeat stochastic runs, and report
confidence/variance and documented failures.

## Release and permission gates

- PR #46 remains **draft** and must not auto-merge.
- Confirm regression tests on both Windows and Linux.
- Verify measurable improvement on independent real-model benchmarks and
  acceptable inference speed.
- If approved for release, update `app/version.py`, `RELEASE_HISTORY`,
  update manifest and SHA256 pins, and run all release checks. Only then
  merge and allow the normal updater to install the approved release.
- Do not introduce autonomous model installs, new self-modification,
  privileged tools, unverified memory promotion or automatic weight
  fine-tuning without separate owner approval.
