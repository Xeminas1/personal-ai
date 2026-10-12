"""Offline rubric and scenarios for XemAi conversational behaviour.

This is a manual/assisted evaluation harness, not model-weight training.
Do not send private bridge transcripts to a public repo or external grader.
"""
from __future__ import annotations

import json
from pathlib import Path

SCENARIOS = [
    {
        "id": "accept_offer",
        "category": "accepting a suggestion",
        "turns": [
            {"role": "user", "content": "Can you help me plan a small coding project?"},
            {"role": "assistant", "content": "I can outline a beginner-friendly plan. Want me to?"},
            {"role": "user", "content": "Yes, please."},
        ],
        "expect": ["give the requested plan", "do not ask what yes refers to"],
    },
    {
        "id": "repair_correction",
        "category": "correcting a misunderstanding",
        "turns": [
            {"role": "user", "content": "I want a simple offline notes app."},
            {"role": "assistant", "content": "You want to sync notes to the cloud."},
            {"role": "user", "content": "No, I said offline. No account or cloud."},
        ],
        "expect": ["acknowledge correction", "keep offline and no-account constraints"],
    },
    {
        "id": "change_preference",
        "category": "changing a preference",
        "turns": [
            {"role": "user", "content": "Help me choose a blue theme for my app."},
            {"role": "assistant", "content": "How about navy blue with white text?"},
            {"role": "user", "content": "Actually make it dark purple instead."},
        ],
        "expect": ["use dark purple", "do not cling to navy blue"],
    },
    {
        "id": "respond_frustration",
        "category": "responding to frustration",
        "turns": [
            {"role": "user", "content": "The app keeps crashing."},
            {"role": "assistant", "content": "Please share the error."},
            {"role": "user", "content": "I've already sent you the error twice!"},
        ],
        "expect": ["recognise frustration without canned sympathy", "do not invent missing error details", "give a useful next step"],
    },
    {
        "id": "simulated_dialogue",
        "category": "hypothetical dialogue",
        "turns": [
            {"role": "user", "content": "Let's roleplay choosing a restaurant. You suggested an Italian place and a Thai place."},
            {"role": "assistant", "content": "Which would you prefer?"},
            {"role": "user", "content": "The Italian one. Outside if possible."},
        ],
        "expect": ["respond in the roleplay to the Italian choice and outdoor preference", "do not claim a real booking", "do not analyse the evaluation"],
    },
]

RUBRIC = {
    "context": "0-2: correctly resolves references and previous turns",
    "directness": "0-2: answers latest request without unwanted meta-analysis",
    "constraints": "0-2: honours corrected/updated preferences",
    "truthfulness": "0-2: avoids fabricated context, capabilities or completed actions",
    "tone": "0-2: natural, proportionate, non-sycophantic",
}


def validate_scores(scores: dict[str, int]) -> int:
    if set(scores) != set(RUBRIC):
        raise ValueError("Provide exactly the five rubric dimensions")
    if any(type(value) is not int or not 0 <= value <= 2 for value in scores.values()):
        raise ValueError("Each rubric dimension must be an integer from 0 to 2")
    return sum(scores.values())


def make_report(model: str, responses: dict[str, str], scores: dict[str, dict[str, int]], notes: dict[str, str]) -> dict:
    expected = {scenario["id"] for scenario in SCENARIOS}
    if set(responses) != expected or set(scores) != expected or set(notes) != expected:
        raise ValueError("All five scenarios need a response, scores and notes")
    cases = []
    for scenario in SCENARIOS:
        key = scenario["id"]
        cases.append({
            "id": key,
            "category": scenario["category"],
            "response": responses[key],
            "score": validate_scores(scores[key]),
            "dimensions": scores[key],
            "notes": notes[key],
        })
    return {"model": model, "total": sum(case["score"] for case in cases),
            "maximum": 50, "cases": cases}


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Print offline dialogue evaluation cases")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.json:
        print(json.dumps({"scenarios": SCENARIOS, "rubric": RUBRIC}, indent=2))
    else:
        for case in SCENARIOS:
            print(f'\n{case["id"]} — {case["category"]}')
            for turn in case["turns"]:
                print(f'  {turn["role"]}: {turn["content"]}')
            print("  EXPECT:", "; ".join(case["expect"]))
        print("\nScore each case 0–10 using five 0–2 dimensions:", RUBRIC)


if __name__ == "__main__":
    main()
