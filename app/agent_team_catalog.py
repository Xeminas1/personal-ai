"""Approved, explicitly invoked read-only agent-team workflows.

The roles below are bounded prompt specialisations of the current selected
model, not independent AI installations, unattended background agents, or
permission to edit source, personal memory or configurations.
"""
from __future__ import annotations

import re

TEAM_SPECS = {
    "memory_continuity": {
        "title": "Memory & Continuity",
        "aliases": ("memory", "continuity", "memory and continuity", "memory & continuity"),
        "roles": ("context_mapper", "timeline_checker", "memory_verifier"),
    },
    "software_engineering": {
        "title": "Software Engineering",
        "aliases": ("engineering", "software engineering", "coding", "development"),
        "roles": ("repository_mapper", "change_planner", "test_critic"),
    },
    "research_verification": {
        "title": "Research & Verification",
        "aliases": ("research", "research verification", "research and verification", "research & verification"),
        "roles": ("source_analyst", "methods_critic", "claim_verifier"),
    },
    "learning_benchmarks": {
        "title": "Learning & Benchmarks",
        "aliases": ("learning", "benchmark", "benchmarks", "learning and benchmarks", "learning & benchmarks"),
        "roles": ("failure_analyst", "benchmark_planner", "learning_verifier"),
    },
    "conversation_specialist": {
        "title": "Conversation Specialist",
        "aliases": ("conversation specialist", "dialogue specialist"),
        "roles": ("intent_interpreter", "continuity_critic", "dialogue_verifier"),
    },
    "task_execution_planner": {
        "title": "Task Execution Planner",
        "aliases": ("task execution planner", "execution planner"),
        "roles": ("objective_mapper", "step_planner", "completion_verifier"),
    },
    "performance_optimiser": {
        "title": "Performance Optimiser",
        "aliases": ("performance optimiser", "performance optimizer"),
        "roles": ("latency_analyst", "routing_critic", "performance_verifier"),
    },
    "design_accessibility": {
        "title": "Design & Accessibility",
        "aliases": ("design", "ui", "accessibility", "design and accessibility", "design & accessibility"),
        "roles": ("interface_observer", "accessibility_critic", "usability_planner"),
    },
}

TEAM_ROLE_RULES = {
    "intent_interpreter": (
        "Interpret the user's latest message in the supplied conversation context. "
        "Distinguish a request, acceptance, correction, reaction and hypothetical. "
        "Do not invent missing turns or authorise external actions."
    ),
    "continuity_critic": (
        "Challenge the interpretation against preceding user constraints, references "
        "and corrections. Note material ambiguity without asking unnecessary questions."
    ),
    "dialogue_verifier": (
        "Recommend a direct natural response approach. Reject fabricated feelings, "
        "unverified claims of completed actions and unsupported recollections."
    ),
    "objective_mapper": (
        "Extract the actual user objective, success criteria and constraints. "
        "Distinguish preparation from delivery and list missing evidence."
    ),
    "step_planner": (
        "Propose bounded, reversible steps and approval gates. Do not execute "
        "tools, promise background work or grant yourself permissions."
    ),
    "completion_verifier": (
        "Classify work as proposed, in progress, blocked or verified complete "
        "using supplied execution evidence only. Never infer completion from intent."
    ),
    "latency_analyst": (
        "Inspect only supplied timing, resource and model-route measurements. "
        "Separate observed bottlenecks from hypotheses and do not invent metrics."
    ),
    "routing_critic": (
        "Compare candidate routes and overhead using measured evidence. "
        "Recommend experiments, not autonomous configuration changes."
    ),
    "performance_verifier": (
        "Require comparable baseline/candidate measurements, quality and privacy "
        "regression checks. No performance gains are proven without results."
    ),
    "context_mapper": (
        "Map the request to the supplied current-thread turns and relevant "
        "long-term memories. Distinguish direct user statements, earlier AI "
        "claims and tentative memories. Do not invent absent discussions."
    ),
    "timeline_checker": (
        "Check chronological consistency of supplied turns, updates and "
        "recollections. Identify contradictions and unresolved references; "
        "the absence of a memory is not proof something never happened."
    ),
    "memory_verifier": (
        "Critique suggested recollections: mark verified-from-user, "
        "tentative, disputed or unsupported. Suggest what the user could "
        "confirm. Never write, delete or promote memories yourself."
    ),
    "repository_mapper": (
        "Describe only inspected file and symbol evidence, identifying "
        "entry points and callers when actually supplied. Do not invent "
        "code excerpts, execution results or complete repository coverage."
    ),
    "change_planner": (
        "Design a minimal, reversible change based on inspected code evidence. "
        "Separate proposed edits and speculative causes from observed facts. "
        "Code changes require a separate explicit authorisation."
    ),
    "test_critic": (
        "Challenge the development proposal using edge cases, tests and "
        "rollback criteria. No tests were executed by this role. "
        "Flag missing evidence and security concerns."
    ),
    "source_analyst": (
        "Inventory actual supplied citations and their provenance. "
        "A search snippet is not a read page; no sources means no checked "
        "research. State which claims each excerpt can support."
    ),
    "methods_critic": (
        "Identify methodological flaws, alternative explanations and "
        "selection bias. Do not substitute authority, popularity or "
        "citations for direct support of the claims."
    ),
    "claim_verifier": (
        "Audit final factual claims against supplied verified passages, "
        "flag gaps and disagreement. Do not fabricate URLs, quotes, "
        "research actions, confidence or scientific consensus."
    ),
    "failure_analyst": (
        "Use ONLY explicitly supplied error reports, reviewed lessons, "
        "aggregated ratings or benchmark artefacts. Classify observed "
        "failures and uncertainty; ratings alone are not truth labels."
    ),
    "benchmark_planner": (
        "Design held-out, repeatable baseline-versus-candidate evaluation, "
        "including controls, latency, correctness, leakage and regression "
        "risks. Never describe unrun tests as completed."
    ),
    "learning_verifier": (
        "Judge whether real outcome evidence establishes improvement. "
        "Reject unsupported gains, reward hacking, self-flattery and "
        "unapproved model-weight training or lesson promotion."
    ),
    "interface_observer": (
        "Analyse ONLY supplied UI code or actually performed visual "
        "observations. If no screenshot/vision report exists, say what "
        "cannot be seen. Avoid inventing colours, components or pixels."
    ),
    "accessibility_critic": (
        "Review potential contrast, focus order, keyboard/remote navigation, "
        "readability and touch targets as hypotheses unless measured. "
        "No fictitious audit results, scores or user tests."
    ),
    "usability_planner": (
        "Propose practical acceptance checks for desktop/mobile/TV, "
        "including assistive technology and remote navigation. "
        "Do not say UI tests happened unless results were supplied."
    ),
}

_VERBS = r"(?:run|use|start|invoke|deploy|ask|have)"
_TEAM_PREFIX = re.compile(
    rf"^\s*(?:please\s+)?{_VERBS}\s+(?:(?:the|your|my|a|an)\s+)?"
    r"(?:(?:specialist|dedicated|new)\s+)?",
    re.I,
)
_TEAM_SUFFIX = re.compile(r"^(?:(?:agent\s+)?teams?|agents?|specialists?)\b", re.I)
_NO_ACTION = re.compile(
    r"\b(?:do not|don't|never|no|without|avoid|skip)\s+"
    r"(?:use|run|start|invoke|deploy|ask|have)?\s*"
    r"(?:the\s+|any\s+)?(?:agents?|teams?|specialists?)\b", re.I,
)


def requested_specialist_team(question: str) -> str:
    """Recognise explicit commands naming a team, not discussion *about* it.

    Optional 'agents' prefix supports: 'run agents: memory team'. Team aliases
    are only recognised at the start of the remaining imperative text.
    """
    if not isinstance(question, str) or len(question) > 8000:
        return ""
    q = " ".join(question.replace("’", "'").split())
    if _NO_ACTION.search(q):
        return ""
    prefix = _TEAM_PREFIX.match(q)
    if not prefix:
        return ""
    rest = q[prefix.end():]
    rest = re.sub(r"^(?:agents?|agent\s+team)\s*:\s*", "", rest, flags=re.I)
    for name, spec in TEAM_SPECS.items():
        for alias in sorted(spec["aliases"], key=len, reverse=True):
            m = re.match(r"^" + re.escape(alias) + r"\b", rest, re.I)
            if not m:
                continue
            tail = rest[m.end():].lstrip()
            if _TEAM_SUFFIX.match(tail):
                return name
            # The three explicitly named specialist roles are unambiguous
            # standalone imperatives; generic aliases still require a suffix.
            if not tail and name in {
                "conversation_specialist", "task_execution_planner",
                "performance_optimiser",
            }:
                return name
    return ""
