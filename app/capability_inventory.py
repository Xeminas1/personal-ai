"""Authoritative XemAi capability inventory and local self-assessment guard.

This module documents *implemented workflows* in the current application.
Roles are not independent minds, background GPU agents or unrestricted tools.
No self-assessment action may change code, models or user settings.
"""
from __future__ import annotations

import json
import re
import re

from .version import VERSION
from .dialogue_intent import dialogue_intent

_AGENT_QUERY = re.compile(
    r"\b(?:all|list|which|what|tell\s+me|name|describe|show)\b.{0,110}"
    r"\b(?:agents?|specialists?|agent\s+roles?)\b.{0,100}"
    r"\b(?:you|your|xemai|current|currently|using|use|have|run)\b"
    r"|\b(?:all|which|what)\s+(?:of\s+)?(?:your\s+)?"
    r"(?:internal\s+|current\s+)?(?:agents?|specialists?)\b"
    r"|\bagents?\s+(?:do|are)\s+you\s+(?:currently\s+)?(?:use|using|run|have)\b",
    re.I,
)
_SELF_ANALYSIS = re.compile(
    r"\b(?:can|could|are)\s+you\s+(?:able\s+to\s+)?"
    r"(?:analyse|analyze|assess|audit|evaluate|inspect|review|examine)\s+"
    r"(?:yourself|your\s+(?:own\s+)?(?:capabilities|architecture|performance|code|state))\b"
    r"|\b(?:can|could)\s+xemai\s+(?:analyse|analyze|audit|assess)\s+(?:itself|its\s+own)\b",
    re.I,
)
_UPDATE_REFLECTION = re.compile(
    r"\b(?:what\s+do\s+you\s+(?:make|think)\s+of|"
    r"how\s+do\s+you\s+(?:view|assess|evaluate|rate)|"
    r"review|assess|summari[sz]e|describe)\b.{0,85}"
    r"\b(?:your|xemai(?:'s)?)\s+(?:current\s+|past\s+|previous\s+|recent\s+)?"
    r"(?:updates?|releases?|development|progress|capabilities)\b"
    r"|\b(?:your|xemai(?:'s)?)\s+(?:update|release)\s+history\b",
    re.I,
)
_COMPARE_AND_PROPOSE = re.compile(r"\b(?:audit|analyse|analyze|review|assess)\b", re.I)
_EXPLICIT_RESEARCH = re.compile(
    r"\b(?:research\s+(?:external|online|independent|latest)|"
    r"search\s+(?:the\s+)?web|look\s+(?:online|up\s+external)|"
    r"find\s+(?:outside|independent)\s+sources)\b", re.I,
)
_ROLES = (
    ("Planning Agent", "User-invoked supervised agent team", "Decomposes an explicitly requested read-only investigation into checks."),
    ("Development Agent", "User-invoked supervised agent team", "Interprets only supplied, approved read-only source evidence; cannot edit or build."),
    ("Vision Agent", "User-invoked supervised agent team", "Interprets supplied PC vision-model observations; cannot directly inspect raw images without a vision service."),
    ("Self-Improvement Agent", "User-invoked supervised self-audit", "Proposes and critiques improvements using a limited capability snapshot and optional saved Technology Watch leads."),
    ("Verification Agent", "User-invoked supervised agent team", "Challenges earlier model outputs; not independent proof."),
    ("Research Specialist", "Optional specialist pass", "Summarises retrieved evidence when enabled; not an independent browser."),
    ("Skyrim Specialist", "Optional specialist pass", "Reviews supplied Skyrim diagnostic context when enabled."),
    ("Reviewer", "Optional specialist pass", "Checks some replies for unsupported conclusions when enabled."),
    ("AI Technology Watch", "User-enabled scheduled feed monitor, not an LLM agent", "Checks bounded official release feeds, records unverified proposals, and never installs them."),
)


_SELF_RELEASE = re.compile(
    r"\b(?:your|xemai(?:'s)?|this (?:ai|assistant|app))\s+"
    r"(?:(?:most|very|latest|recent|last|newest|current|installed|own)\s+){0,4}"
    r"(?:updates?|releases?|changelogs?|versions?)\b", re.I,
)
_LATEST = re.compile(r"\b(?:latest|last|newest|most\s+recent|current)\b", re.I)


def local_question_type(question: str) -> str:
    if not isinstance(question, str) or len(question) > 5000:
        return ""
    q = " ".join(question.replace("’", "'").split())
    if dialogue_intent(q) == "agent_idea":
        # A proposal about future agents is not an inventory request.
        return ""
    # Reflective questions ask for an assessment of several updates,
    # whereas "what was your latest release?" asks for the installed facts.
    if _UPDATE_REFLECTION.search(q):
        return "update_reflection"
    if _SELF_RELEASE.search(q) and _LATEST.search(q):
        return "latest_release"
    if _AGENT_QUERY.search(q):
        return "agent_inventory"
    if _SELF_ANALYSIS.search(q):
        return "self_analysis"
    if _UPDATE_REFLECTION.search(q):
        return "update_reflection"
    return ""


def asks_for_external_research(question: str) -> bool:
    return bool(_EXPLICIT_RESEARCH.search(str(question or "")))


def inventory(config: dict, runtime: dict, release_history: list[tuple[str, str]]) -> dict:
    """Data is an allowlist, never serialise raw secrets, config or user paths."""
    enabled = config.get("agent_team_enabled", True) is True
    specialist_enabled = config.get("specialists_enabled", True) is True
    watch_enabled = config.get("ai_watch_enabled") is True
    roles = []
    for name, trigger, ability in _ROLES:
        if name == "AI Technology Watch":
            active = watch_enabled
        elif name in {"Research Specialist", "Skyrim Specialist", "Reviewer"}:
            active = specialist_enabled
        else:
            active = enabled
        roles.append({
            "name": name,
            "type": trigger,
            "available_or_enabled": active,
            "function": ability,
        })
    return {
        "application_version": VERSION,
        "underlying_model": str(runtime.get("model", "unknown"))[:100],
        "inference_route": str(runtime.get("compute", "unknown"))[:40],
        "agents": roles,
        "agents_are_distinct_models": False,
        "all_roles_run_on_every_turn": False,
        "separate_vision_model_required_for_visual_evidence": True,
        "self_improvement_workflow_available": enabled,
        "user_invocation": "Run a self-improvement audit of XemAi",
        "self_inspection_scope": (
            "safe configured capability snapshot, current release history, "
            "supplied read-only project evidence, saved Technology Watch suggestions; "
            "no access to model internals or full process introspection"
        ),
        "autonomous_self_editing": False,
        "model_weight_training": False,
        "hardware_benchmark_executed": False,
        "release_history": [
            {"version": str(v)[:25], "description": str(desc)[:420]}
            for v, desc in release_history[-7:]
        ],
    }


def inventory_context(data: dict, kind: str) -> str:
    return (
        "AUTHORITATIVE XEMAI CURRENT CAPABILITIES — LOCAL APPLICATION INVENTORY\n"
        "This inventory is constructed by XemAi's running application, not "
        "from generic web search, model training memories or an earlier assistant. "
        "Answer the user's actual question FIRST. If asked what agents are in "
        "use, name the available roles and explain which are optional or "
        "disabled. They are distinct prompts/passes and a feed monitor, "
        "NOT nine autonomous AIs. If asked whether you can analyse yourself, "
        "answer YES, within the scope of the on-demand supervised self-audit; "
        "do not claim direct introspection of model weights or unrestricted "
        "source-code access. If asked about updates, use release-history facts "
        "and distinguish implemented features from measured improvements. "
        "Implementation is not an independently benchmarked success. "
        "No tool/network lookup is needed unless the latest user explicitly "
        "asks for outside research.\n"
        + json.dumps({"question_type": kind, "inventory": data}, ensure_ascii=False)[:12500]
    )


def direct_answer(data: dict, kind: str) -> str:
    """Grounded deterministic response to simple capability questions.

    An audit request remains an agent task; this only handles informational
    questions, never auto-runs, installs or modifies anything.
    """
    if kind == "agent_inventory":
        items = [
            f"- **{row['name']}** — {row['function']} "
            f"({'enabled' if row['available_or_enabled'] else 'currently disabled'}; {row['type']})."
            for row in data["agents"]
        ]
        return (
            "XemAi currently implements these agent roles and monitoring/specialist workflows:\n\n"
            + "\n".join(items)
            + "\n\nThey do not all run on every question. Most are sequential "
            "passes using the selected language model; the Vision Agent "
            "requires observations from a separate vision service, while "
            "AI Technology Watch is a feed monitor. None can independently "
            "rewrite XemAi, install models or modify XemTV."
        )
    if kind == "self_analysis":
        return (
            "**Yes, within limits.** XemAi can run an on-demand, supervised "
            "self-improvement audit to review its current capability snapshot, "
            "release history, saved AI Technology Watch leads and supplied "
            "read-only evidence. Its Planning, Self-Improvement and Verification "
            "agents can propose measurable changes and challenge assumptions. "
            "This is a limited software/configuration analysis, not direct "
            "inspection of model thoughts or weights. It cannot independently "
            "edit its code or prove an improvement without comparative tests.\n\n"
            f"To run it, ask: **{data['user_invocation']}**."
        )
    if kind == "latest_release":
        current = str(data["application_version"])
        matching = next(
            (r for r in data.get("release_history", [])
             if r.get("version") == current), None
        )
        if matching is None:
            return (
                f"I can see my running application version: **XemAi v{current}**. "
                "I don't have a verified description of what changed in this "
                "particular release, so I won't guess. I can still report "
                "the version from my own application."
            )
        return (
            f"Yes. I'm running **XemAi v{current}**. My current release "
            f"notes say: **{matching['description']}**\n\n"
            "These are the application's bundled release notes, not "
            "evidence that my underlying model weights changed or that "
            "performance improved in independent tests."
        )
    if kind == "update_reflection":
        releases = data["release_history"][-5:]
        lines = [
            f"- **v{row['version']}**: {row['description']}"
            for row in releases
        ]
        return (
            "XemAi's recent updates added concrete application features, but "
            "**passing implementation tests is not the same as measuring a gain "
            "in model accuracy or independent reasoning**.\n\n"
            + "\n".join(lines)
            + "\n\nMy assessment: the biggest improvements are local, "
            "controlled workflows and more grounded answers about current "
            "capabilities. The unresolved weaknesses are reliable multi-step "
            "reasoning, distinguishing source evidence from vendor claims, "
            "software engineering accuracy and measured model comparisons. "
            "The next useful step is a repeatable benchmark suite against "
            "the previous release, without altering any source or models."
        )
    return ""


def audit_response_needs_retry(answer: str, report: dict) -> bool:
    """Reject a plausible but unrelated comparison instead of echoing it."""
    if report.get("mode") != "self_audit":
        return False
    value = str(answer or "").lower()
    if len(value) < 200:
        return True
    # Qwen sometimes calls speculative *future* outcomes "benchmarked gains".
    # A locally implemented workflow is evidence of software, not a measured
    # improvement in accuracy, VRAM, memory or model reasoning.
    if re.search(r"\bbenchmarked gains?\b", value) and re.search(
        r"\b(?:potential|expected|hypothetical)\b.{0,120}"
        r"\b(?:gain|improvement|reduction|speed|latency)\b",
        value, re.S,
    ):
        return True
    if "self-audit failed due to missing evidence" in value:
        return True
    if "file does not exist" in value and not report.get("source_evidence_provided"):
        return True
    if not any(word in value for word in ("xemai", "my current", "my capabilities")):
        return True
    if not any(word in value for word in ("planning", "verif", "self-improvement", "agent", "auditor")):
        return True
    if not any(word in value for word in ("limitation", "weakness", "gap", "risk", "uncertain")):
        return True
    if not any(word in value for word in ("benchmark", "test", "measure")):
        return True
    return False


def audit_fallback(data: dict, report: dict) -> str:
    completed = [r["role"] for r in report.get("agents", []) if r.get("status") == "completed"]
    missing = [r["role"] for r in report.get("agents", []) if r.get("status") != "completed"]
    return (
        f"**XemAi v{data['application_version']} self-improvement assessment**\n\n"
        f"Available supervised roles: {', '.join(r['name'] for r in data['agents'][:5])}. "
        f"This request attempted the Planning, Self-Improvement and Verification "
        f"passes. Completed: {', '.join(completed) or 'none'}; "
        f"unavailable: {', '.join(missing) or 'none'}.\n\n"
        "**Implemented:** on-demand supervised read-only investigations, "
        "persistent local chat/memory, optional hybrid model inference, and "
        "opt-in AI Technology Watch. These are software capabilities, not "
        "benchmarked proof of improved reasoning.\n\n"
        "**Limitations and proposed tests:** (1) Benchmark screenshot "
        "identification with fixed annotated reference images; (2) measure "
        "accuracy on Kotlin code navigation and multi-file bug investigations; "
        "(3) evaluate source-grounded answer relevance and memory retrieval "
        "on repeatable questions across releases. Each test needs baseline "
        "results, candidate results, and independent review.\n\n"
        "**Verifier caution:** agent passes share a base model and may repeat "
        "the same mistakes. Their notes are not independent validation; "
        "no XemAi-vs-ChatGPT comparison was run. Do not install, rewrite or "
        "change permissions on these unverified suggestions."
    )
