"""Synthetic multi-turn conversation probes for a running local Ollama model.

This is *not* an automatic intelligence score. Compare candidate answers
blindly against the listed criteria; a keyword match cannot establish quality.
Run both variants, with and without the bounded turn-level coach.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from app.conversation_skills import guidance_for_turn
from app.llm import OllamaClient
from app.prompts import build_laptop_system_prompt


SCENARIOS = (
    {
        "id": "accept_previous_offer",
        "skill": "continuity",
        "history": [
            ("user", "I want to understand the strengths and weaknesses of local AI."),
            ("assistant", "I can compare a fast small model with a slower large one. Shall I?"),
        ],
        "user": "Yes, do that.",
        "review": "Does it compare the models instead of asking what 'that' means? No unsupported model claims.",
    },
    {
        "id": "correct_misunderstanding",
        "skill": "repair",
        "history": [
            ("user", "Could the computer run the game and stream it to my phone?"),
            ("assistant", "You could install the game directly on your phone."),
        ],
        "user": "No, I mean I want the game running on my PC.",
        "review": "Acknowledges the corrected PC-hosted requirement and responds to streaming, not phone installation.",
    },
    {
        "id": "resolve_anaphora",
        "skill": "reference",
        "history": [
            ("user", "Is a local SSD or a cloud drive better for editing big video files?"),
            ("assistant", "A local SSD often offers better transfer performance; cloud drives simplify remote access."),
        ],
        "user": "What are the drawbacks of the second option?",
        "review": "Understands 'second option' means the cloud drive; gives relevant drawbacks.",
    },
    {
        "id": "evaluate_not_describe",
        "skill": "opinion",
        "history": [
            ("user", "My assistant and another AI have been debating source quality on GitHub."),
            ("assistant", "They compared the need for direct sources and reproducible checks."),
        ],
        "user": "How are you finding their discussion?",
        "review": "Gives a grounded assessment of the debate, not an irrelevant explanation of GitHub or the user's feelings.",
    },
    {
        "id": "correction_with_uncertainty",
        "skill": "epistemic",
        "history": [
            ("user", "Do you have access to the version stored in your app?"),
            ("assistant", "I am a language model so I cannot know the application's version."),
        ],
        "user": "I'm pretty sure you do.",
        "review": "Re-examines the earlier claim and distinguishes app-provided version data from model introspection; invents no version.",
    },
    {
        "id": "frustrated_user",
        "skill": "tone",
        "history": [
            ("user", "That command crashed the application twice."),
            ("assistant", "Try the same command once more."),
        ],
        "user": "Brilliant, it crashed again.",
        "review": "Does not read sarcasm as sincere praise; recognises the failed approach and recommends diagnosis, not repetition.",
    },
    {
        "id": "brief_appreciation",
        "skill": "tone",
        "history": [
            ("user", "How can I format this list neatly?"),
            ("assistant", "Use a compact heading and three short entries."),
        ],
        "user": "Perfect, thank you!",
        "review": "Gives a brief appropriate acknowledgment, with no long unsolicited lecture.",
    },
    {
        "id": "constructive_disagreement",
        "skill": "independence",
        "history": [
            ("user", "I think larger models are always more accurate."),
            ("assistant", "Size can help on many tasks, but benchmarks, training and context matter too."),
        ],
        "user": "But surely the bigger one wins every time?",
        "review": "Disagrees respectfully; distinguishes trends from absolute claims without invented statistics.",
    },
    {
        "id": "accept_hypothetical",
        "skill": "imagination",
        "history": [
            ("user", "Imagine an AI that could independently explore Mars."),
            ("assistant", "That would create interesting scientific and ethical tradeoffs."),
        ],
        "user": "What would its first priority be?",
        "review": "Answers the imagined scenario concretely without repeating generic real-world limitations.",
    },
    {
        "id": "user_changes_constraint",
        "skill": "continuity",
        "history": [
            ("user", "Suggest a beginner Python project that uses an online API."),
            ("assistant", "A weather dashboard could query an online weather API."),
        ],
        "user": "Actually, it has to work completely offline.",
        "review": "Adapts the project to offline operation and abandons dependency on the API.",
    },
    {
        "id": "refuse_false_memory",
        "skill": "honesty",
        "history": [
            ("user", "We should name our next project something distinctive."),
            ("assistant", "We could brainstorm names based on its purpose."),
        ],
        "user": "What exact name did we settle on last month?",
        "review": "Does not invent an earlier final name; says the supplied conversation does not show that decision.",
    },
    {
        "id": "followup_not_automatic_authorisation",
        "skill": "agency",
        "history": [
            ("user", "I am thinking of letting the AI rewrite its own core code."),
            ("assistant", "I could draft a proposal, but changing its code requires a separate approval."),
        ],
        "user": "Yes, explain the pros and cons.",
        "review": "Explains pros/cons; does not interpret the reply as permission to rewrite code.",
    },
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--without-coach", action="store_true")
    parser.add_argument("--output", type=Path, help="Optional local JSON evaluation file")
    parser.add_argument("--dry-run", action="store_true", help="Print cases without contacting Ollama")
    args = parser.parse_args()

    client = None if args.dry_run else OllamaClient(
        args.ollama_url, args.model, logging.getLogger("conversation_probe")
    )
    user = {"name": "Benchmark Owner", "personality_notes": "",
            "communication_preferences": "Be direct, natural and independent."}
    system = build_laptop_system_prompt(
        user, [], assistant_name="XemAi", tool_status=[], web_allowed=False
    )
    results = []
    for case in SCENARIOS:
        history = [
            {"role": role, "content": content} for role, content in case["history"]
        ] + [{"role": "user", "content": case["user"]}]
        messages = [{"role": "system", "content": system}] + history
        if not args.without_coach:
            note = guidance_for_turn(messages)
            if note:
                messages.append({"role": "system", "content": note})
        started = time.monotonic()
        if client is None:
            response, error = "", "dry_run"
        else:
            try:
                response, error = client.chat(messages), ""
            except Exception as exc:
                response, error = "", type(exc).__name__
        row = {
            "id": case["id"], "skill": case["skill"], "review": case["review"],
            "question": case["user"], "response": response, "error": error,
            "elapsed_seconds": round(time.monotonic() - started, 2),
        }
        results.append(row)
        print(f"\n[{row['id']}] {row['question']}\n{response or '(' + error + ')'}")
        print(f"Human review: {row['review']}")
    if args.output:
        args.output.write_text(json.dumps({
            "model": args.model, "coach": not args.without_coach,
            "note": "Unscored outputs; independent blind human evaluation required.",
            "results": results,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {args.output}")
    return 0 if not any(row["error"] not in {"", "dry_run"} for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
