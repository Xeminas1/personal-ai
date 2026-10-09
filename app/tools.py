from __future__ import annotations

import ast
import json
import math
import operator
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .secrets import load_ollama_api_key


class ToolError(RuntimeError):
    pass


def _normalized_query(text: str) -> str:
    lower = " ".join(str(text).lower().replace("’", "'").replace("‘", "'").split())
    return re.sub(r"\bwhat(?:'s|s)\b", "what is", lower)


def _web_search_disallowed(text: str) -> bool:
    lower = _normalized_query(text)
    return bool(re.search(
        r"\b(?:don'?t|do not)\s+(?:search|research|browse|verify)\b"
        r"|\b(?:don'?t|do not)\s+look(?:\s+(?:it|this|that))?\s+up\b"
        r"|\b(?:no|without)\s+(?:web|internet|browsing|research(?:ing)?|search(?:ing)?)\b"
        r"|\b(?:don'?t|do not)\s+(?:use|access)\s+(?:the\s+)?(?:web|internet)\b",
        lower,
    ))


def should_force_web_search(text: str) -> bool:
    """
    Deterministic routing for requests that clearly require live search.
    This avoids relying entirely on a small local model to decide whether
    to call the web_search tool.
    """
    lower = _normalized_query(text)
    if _web_search_disallowed(text):
        return False
    explicit_phrases = (
        "search the web",
        "search online",
        "browse the web",
        "browse online",
        "look it up",
        "look that up",
        "look this up",
        "look up ",
        "check the web",
        "check online",
        "find online",
    )
    if any(phrase in lower for phrase in explicit_phrases):
        return True

    freshness_terms = (
        "latest ",
        "latest news",
        "recent news",
        "current news",
        "today's news",
        "todays news",
        "up to date",
        "up-to-date",
        "what happened today",
    )
    return any(term in lower for term in freshness_terms)


_RESEARCH_STOPWORDS = {
    "about", "after", "again", "also", "been", "being", "best", "could",
    "does", "from", "have", "into", "just", "more", "most", "much",
    "should", "that", "their", "there", "these", "they", "this", "those",
    "what", "when", "where", "which", "with", "would", "your",
}

_TOPIC_STOPWORDS = _RESEARCH_STOPWORDS | {
    "a", "an", "and", "any", "are", "as", "at", "be", "but", "by", "can",
    "did", "do", "for", "he", "her", "his", "i", "if", "in", "is", "it",
    "me", "my", "no", "not", "of", "on", "or", "our", "so", "the", "to",
    "us", "was", "we", "were", "why", "will", "you", "please", "using", "use",
    "source", "sources", "cite", "citing", "citation", "citations", "reference",
    "references", "evidence", "proof", "research", "verify", "verification",
    "check", "checked", "fact", "facts", "factcheck", "information", "claim",
    "claims", "answer", "answers", "response", "previous", "last", "above",
    "saying", "said", "say", "show", "give", "get", "got", "tell", "support",
    "look", "up", "online", "web", "search", "browse", "reliable", "official",
    "primary", "reputable", "back", "backed", "true", "really", "about",
    "famous", "fame", "good", "great", "better", "correct", "wrong", "incorrect",
    "correction", "actually", "instead", "rather", "them", "they", "its", "it's",
    "provide", "provided", "link", "links", "quote", "quotes", "fact-check",
}


def _topic_word(word: str) -> str:
    word = word.removesuffix("'s")
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _topic_terms(text: str) -> set[str]:
    return {
        _topic_word(word) for word in re.findall(r"[a-z0-9][a-z0-9'\-]*", _normalized_query(text))
        if len(word) >= 2 and word not in _TOPIC_STOPWORDS
        and _topic_word(word) not in _TOPIC_STOPWORDS
    }


def _generic_research_followup(text: str) -> bool:
    lower = _normalized_query(text)
    intent = re.search(
        r"\b(?:sources?|citations?|references?|cite|evidence|proof|verify|verification|factcheck|research)\b"
        r"|\b(?:fact[- ]check|check (?:this|that)|is (?:this|that) true|look it up)\b",
        lower,
    )
    if not intent and not should_force_web_search(text):
        return False
    return not _topic_terms(text)


def research_query_for_turn(text: str, previous_user_messages) -> str:
    """Resolve generic sourcing follow-ups from bounded prior user topics only.

    The caller supplies visible USER text, never assistant claims or attachments.
    This query is tool input; the current user's actual message remains intact.
    """
    if not isinstance(text, str):
        return ""
    if _web_search_disallowed(text) or not _generic_research_followup(text):
        return text
    if not isinstance(previous_user_messages, (list, tuple)):
        return text
    topics = [" ".join(value.split()) for value in previous_user_messages[-12:]
              if isinstance(value, str) and value.strip() and _topic_terms(value)
              and not _generic_research_followup(value)]
    if not topics:
        return text
    selected = [topics[-1]]
    latest = _normalized_query(selected[0])
    correction = re.search(r"\b(?:actually|wrong|incorrect|correction|instead|not)\b|\bi meant\b", latest)
    if correction and len(topics) > 1 and _topic_terms(topics[-2]) & _topic_terms(selected[0]):
        selected.insert(0, topics[-2])
    suffix = " verify sources"
    limit = (1200 - len(suffix) - (3 if len(selected) == 2 else 0)) // len(selected)
    return " ; ".join(value[:limit] for value in selected) + suffix

_REPUTABLE_DOMAINS = {
    "skse.silverlock.org": (108, "Official Skyrim Script Extender source"),
    "loot.github.io": (102, "Official LOOT documentation"),
    "wiki.nexusmods.com": (92, "Nexus Mods mod-manager documentation"),
    "nexusmods.com": (78, "Mod hosting; verify the specific mod author's description and requirements"),
    "pubmed.ncbi.nlm.nih.gov": (120, "PubMed / biomedical research"),
    "ncbi.nlm.nih.gov": (112, "NCBI / biomedical research"),
    "nih.gov": (112, "US National Institutes of Health"),
    "cochranelibrary.com": (120, "Cochrane systematic reviews"),
    "who.int": (112, "World Health Organization"),
    "nice.org.uk": (114, "NICE clinical guidance"),
    "nhs.uk": (108, "NHS guidance"),
    "cdc.gov": (112, "US CDC"),
    "fda.gov": (108, "US FDA"),
    "gov.uk": (100, "UK government"),
    "jamanetwork.com": (104, "Peer-reviewed medical journal"),
    "nejm.org": (104, "Peer-reviewed medical journal"),
    "thelancet.com": (104, "Peer-reviewed medical journal"),
    "bmj.com": (102, "Peer-reviewed medical journal"),
    "nature.com": (96, "Scientific journal / publisher"),
    "science.org": (96, "Scientific journal / publisher"),
    "docs.python.org": (104, "Official Python documentation"),
    "developer.mozilla.org": (98, "MDN technical documentation"),
    "w3.org": (104, "Web standards body"),
    "nist.gov": (108, "US standards / research agency"),
    "plos.org": (98, "Peer-reviewed scientific journal"),
    "frontiersin.org": (90, "Peer-reviewed scientific publisher"),
    "academic.oup.com": (98, "Peer-reviewed academic publisher"),
    "cambridge.org": (94, "Academic publisher"),
    "link.springer.com": (90, "Academic publisher"),
    "sciencedirect.com": (90, "Academic publisher"),
    "cell.com": (100, "Peer-reviewed scientific journal"),
    "pnas.org": (100, "Peer-reviewed scientific journal"),
    "royalsocietypublishing.org": (98, "Peer-reviewed scientific journal"),
    "arxiv.org": (70, "Academic preprint repository"),
    "ietf.org": (104, "Internet standards body"),
    "rfc-editor.org": (104, "Internet standards publication"),
    "sec.gov": (108, "US financial regulator"),
    "fca.org.uk": (106, "UK financial regulator"),
    "bankofengland.co.uk": (106, "UK central bank"),
    "ons.gov.uk": (106, "UK official statistics"),
    "imf.org": (96, "International financial institution"),
    "worldbank.org": (96, "International development institution"),
    "developers.google.com": (86, "Official vendor documentation"),
    "docs.github.com": (86, "Official vendor documentation"),
    "microsoft.com": (82, "Official vendor source"),
    "apple.com": (82, "Official vendor source"),
    "openai.com": (82, "Official vendor source"),
    "nvidia.com": (82, "Official vendor source"),
}

_LOW_QUALITY_DOMAINS = {
    "reddit.com", "quora.com", "pinterest.com", "tiktok.com",
    "facebook.com", "instagram.com", "x.com", "twitter.com",
    "medium.com",
}

_HEALTH_RESEARCH_TERMS = {
    "health", "medical", "medicine", "symptom", "symptoms", "disease",
    "infection", "cold", "flu", "virus", "pain", "treatment", "drug",
    "medication", "supplement", "diet", "exercise", "sleep", "blood",
    "heart", "cancer", "testosterone", "therapy",
}

_SCIENCE_RESEARCH_TERMS = {
    "study", "studies", "research", "evidence", "scientific", "science",
    "peer reviewed", "systematic review", "meta-analysis", "trial",
    "randomized", "randomised", "paper", "journal",
}


def should_research_query(text: str) -> bool:
    """
    Deterministically decide whether outside evidence would materially improve
    the answer. This is intentionally broader than freshness-only web routing
    but excludes casual, creative and XemAi-local questions.
    """
    lower = _normalized_query(text)
    if not lower:
        return False

    if _web_search_disallowed(text):
        return False

    casual_or_local = (
        "how are you", "how do you feel", "who are you", "what is your name",
        "what model are you running", "what version are you",
        "new chat", "rename this chat",
    )
    if any(term in lower for term in casual_or_local):
        return False

    creative_starts = (
        "write me ", "write a ", "rewrite ", "reword ", "brainstorm ",
        "give me names", "give me name", "make up ", "roleplay ",
        "create a story", "create a character",
    )
    if lower.startswith(creative_starts):
        return False

    explicit = (
        "research ", "research this", "source", "sources", "cite", "citation",
        "evidence", "study", "studies", "paper", "peer reviewed",
        "peer-reviewed", "backed by", "what does the research",
        "what do studies", "scientific evidence",
        "verify", "verification", "fact check", "fact-check", "factcheck", "references",
        "check this", "check that", "is that true", "is this true",
    )
    if any(term in lower for term in explicit):
        return True

    tokens = set(re.findall(r"[a-z0-9][a-z0-9'\-]+", lower))
    if tokens & _HEALTH_RESEARCH_TERMS:
        return True
    if any(term in lower for term in _SCIENCE_RESEARCH_TERMS):
        return True

    factual_starts = (
        "what is ", "what are ", "why does ", "why do ", "why is ",
        "how does ", "how do ", "how can ", "is it ", "are there ",
        "does ", "do ", "can ", "should ", "which ", "when ", "where ",
        "who ", "what causes ", "what's the best", "what is the best",
    )
    return len(lower) >= 20 and lower.startswith(factual_starts)


def _research_terms(query: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9][a-z0-9'\-]+", query.lower())
        if len(token) >= 4 and token not in _RESEARCH_STOPWORDS
    }


def _source_host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _source_authority(url: str, title: str = "", content: str = "") -> tuple[int, str]:
    host = _source_host(url)

    score = 0
    label = "General web source"

    for domain, (domain_score, domain_label) in _REPUTABLE_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            score = max(score, domain_score)
            label = domain_label
            break

    if host.endswith(".gov") or host.endswith(".gov.uk"):
        score = max(score, 100)
        label = "Government / public authority"
    elif host.endswith(".edu") or host.endswith(".ac.uk"):
        score = max(score, 88)
        label = "Academic institution"

    if any(host == d or host.endswith("." + d) for d in _LOW_QUALITY_DOMAINS):
        score -= 100
        label = "Low-priority community / social source"

    evidence_text = f"{title} {content}".lower()
    if any(term in evidence_text for term in (
        "systematic review", "meta-analysis", "meta analysis",
        "randomized controlled trial", "randomised controlled trial",
        "clinical guideline", "practice guideline",
    )):
        score += 22
        if label == "General web source":
            label = "Research / evidence source"
    elif any(term in evidence_text for term in (
        "peer reviewed", "journal", "study", "trial", "guideline",
    )):
        score += 10

    if not content.strip():
        score -= 10

    return score, label


def _research_query_variant(query: str) -> str:
    lower = query.lower()
    tokens = set(re.findall(r"[a-z0-9][a-z0-9'\-]+", lower))
    if tokens & _HEALTH_RESEARCH_TERMS:
        return f"{query} systematic review PubMed NHS NICE evidence"
    if any(term in lower for term in _SCIENCE_RESEARCH_TERMS):
        return f"{query} systematic review meta-analysis peer reviewed"
    if any(term in lower for term in (
        "code", "python", "javascript", "windows", "android", "api",
        "software", "programming", "browser",
    )):
        return f"{query} official documentation specification"
    return f"{query} primary source official evidence"


def extract_relevant_passage(content: str, query: str, max_chars: int = 1200) -> str:
    """Keep a bounded topical passage and nearby qualifications from page text."""
    clean = " ".join(str(content).split())
    if not clean:
        return ""
    limit = max(1, min(2400, int(max_chars)))
    terms = _topic_terms(query)
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    ranked = [(len(terms & _topic_terms(sentence)), -index, index)
              for index, sentence in enumerate(sentences)]
    overlap, _, best = max(ranked)
    if terms and not overlap:
        return ""

    focus = sentences[best]
    if len(focus) > limit:
        # Very long sentences have no usable boundary. Keep the topic in the
        # bounded fragment; provenance marks the excerpt as incomplete.
        anchor = next((match.start() for match in re.finditer(r"[a-z0-9][a-z0-9'\-]*", focus.lower())
                       if _topic_word(match.group()) in terms), 0)
        start = max(0, min(anchor - limit // 4, len(focus) - limit))
        return focus[start:start + limit]

    start = end = best
    size = len(focus)
    # Following sentences often contain a limitation or conflicting result.
    for index in range(best + 1, min(len(sentences), best + 3)):
        if size + 1 + len(sentences[index]) > limit:
            break
        end, size = index, size + 1 + len(sentences[index])
    if best and size + 1 + len(sentences[best - 1]) <= limit:
        start = best - 1
    return " ".join(sentences[start:end + 1])


def extract_exact_quote(content: str, query: str, max_words: int = 24) -> str:
    """
    Pick a complete short sentence from fetched page text. Never cut off a
    qualification to fit the quotation limit; the passage carries that context.
    """
    clean = " ".join(str(content).split())
    if not clean:
        return ""

    terms = _topic_terms(query)
    candidates = re.split(r"(?<=[.!?])\s+", clean)
    ranked = []

    for index, sentence in enumerate(candidates[:180]):
        words = sentence.split()
        if len(words) < 6:
            continue
        lower = sentence.lower()
        overlap = len(terms & _topic_terms(sentence))
        if terms and not overlap:
            continue
        evidence_bonus = sum(
            1 for marker in (
                "found", "associated", "increased", "decreased", "reduced",
                "recommend", "evidence", "concluded", "results", "risk",
                "effective", "benefit", "compared",
            )
            if marker in lower
        )
        length_bonus = 2 if 8 <= len(words) <= 35 else 0
        ranked.append((overlap * 5 + evidence_bonus + length_bonus, -index, sentence))

    if not ranked:
        return ""

    ranked.sort(reverse=True)
    sentence = ranked[0][2]
    if len(sentence.split()) > max(1, min(25, int(max_words))):
        return ""
    if not re.search(r"[.!?][\"'’”)]*$", sentence):
        return ""
    return sentence


def format_research_appendix(bundle: dict[str, Any]) -> str:
    sources = list(bundle.get("sources") or [])
    if not sources:
        return ""

    all_opened = all(source.get("content_origin") == "fetched_page"
                     and source.get("page_fetched") is True for source in sources)
    lines = ["Sources read:" if all_opened else "Sources retrieved:"]
    if all_opened:
        lines.append("Pages read; each citation still needs to support its claim.")
    for source in sources:
        sid = int(source.get("id", len(lines)))
        title = str(source.get("title") or source.get("domain") or "Source")
        authority = str(source.get("authority") or "Source")
        opened = source.get("content_origin") == "fetched_page" and source.get("page_fetched") is True
        quote = (str(source.get("quote") or "").strip()
                 if opened and source.get("quote_verified_from_fetched_page") is True else "")
        url = str(source.get("url") or "").strip()
        lines.append(f"[{sid}] {title} — {authority}")
        lines.append("Page read." if opened else "Search result snippet; page not read.")
        if quote:
            lines.append(f'> "{quote}"')
        if url:
            lines.append(url)
    return "\n".join(lines)


def _prefer_independent_candidates(ordered: list[dict]) -> list[dict]:
    """Prefer another host only among equally topical, equally strong results."""
    remaining, result, used = list(ordered), [], set()
    while remaining:
        index = 0
        first = remaining[0]
        if first["domain"] and first["domain"] in used:
            index = next((i for i, item in enumerate(remaining)
                          if item["domain"] and item["domain"] not in used
                          and item["topic_overlap"] == first["topic_overlap"]
                          and item.get("page_fetched") == first.get("page_fetched")
                          and item["base_authority"] >= first["base_authority"]), 0)
        selected = remaining.pop(index)
        result.append(selected)
        used.add(selected["domain"])
    return result



class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        self.parts.append(text)


_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_ALLOWED_UNARY = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_ALLOWED_FUNCS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
}


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 20:
            raise ToolError("Exponent is too large.")
        return _ALLOWED_BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
        return _ALLOWED_UNARY[type(node.op)](_safe_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = _ALLOWED_FUNCS.get(node.func.id)
        if fn is None:
            raise ToolError("Function is not allowed.")
        return fn(*[_safe_eval(arg) for arg in node.args])
    raise ToolError("Expression contains unsupported syntax.")


class ToolRegistry:
    def __init__(self, base_dir: Path, data_dir: Path, logger):
        self.base_dir = base_dir.resolve()
        self.data_dir = data_dir.resolve()
        self.workspace = (base_dir / "workspace").resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.logger = logger

    @property
    def web_search_enabled(self) -> bool:
        return bool(load_ollama_api_key(self.data_dir))

    def status_lines(self) -> list[str]:
        return [
            "calculator: enabled",
            "current_time: enabled",
            "web_fetch: enabled (direct HTTPS/HTTP page fetch)",
            (
                "web_search: configured (run /webtest to verify connection)"
                if self.web_search_enabled
                else "web_search: disabled (run /websetup to configure)"
            ),
            (
                "evidence_research: enabled (reputable-source ranking + verbatim quote extraction)"
                if self.web_search_enabled
                else "evidence_research: unavailable until web_search is configured"
            ),
            "workspace_list: enabled",
            "workspace_read: enabled",
            "workspace_write: enabled",
            "feedback learning: enabled",
        ]

    def definitions(self) -> list[dict[str, Any]]:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "calculator",
                    "description": "Safely calculate a mathematical expression.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expression": {
                                "type": "string",
                                "description": "Math expression such as (25*4)+sqrt(81)"
                            }
                        },
                        "required": ["expression"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "current_time",
                    "description": "Get the current date and time for a timezone.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "timezone": {
                                "type": "string",
                                "description": "IANA timezone such as Europe/London. Use local for computer local time."
                            }
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "web_fetch",
                    "description": "Fetch current text from a specific HTTP or HTTPS webpage.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "Full webpage URL"}
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "workspace_list",
                    "description": "List files and folders inside the AI's local workspace directory.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative workspace path; default ."}
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "workspace_read",
                    "description": "Read a UTF-8 text file inside the local workspace.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative path inside workspace"},
                            "max_chars": {"type": "integer", "description": "Maximum characters to return"}
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "workspace_write",
                    "description": "Create or replace a UTF-8 text file inside the local workspace. Only use when the user asks to create or change a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative path inside workspace"},
                            "content": {"type": "string", "description": "Complete file contents"}
                        },
                        "required": ["path", "content"],
                    },
                },
            },
        ]

        if self.web_search_enabled:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "description": "Search the live web for current information. Use for recent, changing, or externally verifiable facts.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "Search query"},
                                "max_results": {
                                    "type": "integer",
                                    "description": "Number of results, 1-10"
                                },
                            },
                            "required": ["query"],
                        },
                    },
                }
            )
        if self.web_search_enabled:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "research_evidence",
                        "description": (
                            "Research a factual question using ranked reputable sources. "
                            "Returns numbered sources, short evidence excerpts and verbatim "
                            "quote candidates. Prefer this over plain web_search when the "
                            "user asks for evidence, studies, health/science facts or citations."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Factual question or research query"
                                },
                                "max_sources": {
                                    "type": "integer",
                                    "description": "Maximum sources to return, 1-5"
                                },
                            },
                            "required": ["query"],
                        },
                    },
                }
            )

        return tools

    def _safe_workspace_path(self, relative: str) -> Path:
        relative = (relative or ".").strip()
        target = (self.workspace / relative).resolve()
        if target != self.workspace and self.workspace not in target.parents:
            raise ToolError("Path escapes the allowed workspace.")
        return target

    def execute(self, name: str, arguments: dict[str, Any] | None) -> str:
        args = arguments or {}
        self.logger.info("Tool call | name=%s", name)

        try:
            if name == "calculator":
                result = self.calculator(str(args.get("expression", "")))
            elif name == "current_time":
                result = self.current_time(str(args.get("timezone", "local")))
            elif name == "web_search":
                result = self.web_search(
                    str(args.get("query", "")),
                    int(args.get("max_results", 5) or 5),
                )
            elif name == "web_fetch":
                result = self.web_fetch(str(args.get("url", "")))
            elif name == "research_evidence":
                result = self.research_evidence(
                    str(args.get("query", "")),
                    int(args.get("max_sources", 3) or 3),
                )
            elif name == "workspace_list":
                result = self.workspace_list(str(args.get("path", ".")))
            elif name == "workspace_read":
                result = self.workspace_read(
                    str(args.get("path", "")),
                    int(args.get("max_chars", 20000) or 20000),
                )
            elif name == "workspace_write":
                result = self.workspace_write(
                    str(args.get("path", "")),
                    str(args.get("content", "")),
                )
            else:
                raise ToolError(f"Unknown tool: {name}")
        except Exception as e:
            self.logger.warning("Tool failure | name=%s error=%r", name, e)
            return json.dumps({"ok": False, "error": str(e)})

        self.logger.info("Tool success | name=%s", name)
        return json.dumps({"ok": True, "result": result}, ensure_ascii=False)

    def calculator(self, expression: str):
        if not expression or len(expression) > 500:
            raise ToolError("Expression is empty or too long.")
        tree = ast.parse(expression, mode="eval")
        result = _safe_eval(tree)
        if isinstance(result, float) and not math.isfinite(result):
            raise ToolError("Result is not finite.")
        return result

    def current_time(self, timezone: str = "local") -> dict[str, str]:
        if not timezone or timezone.lower() == "local":
            now = datetime.now().astimezone()
        else:
            try:
                now = datetime.now(ZoneInfo(timezone))
            except Exception as e:
                raise ToolError(f"Unknown timezone: {timezone}") from e
        return {
            "iso": now.isoformat(timespec="seconds"),
            "timezone": str(now.tzinfo),
        }

    def _ollama_web_search_request(
        self,
        *,
        key: str,
        query: str,
        max_results: int = 5,
        timeout: int = 45,
    ) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise ToolError("Search query is empty.")

        max_results = max(1, min(10, int(max_results)))
        payload = json.dumps(
            {"query": query, "max_results": max_results}
        ).encode("utf-8")
        req = urllib.request.Request(
            "https://ollama.com/api/web_search",
            data=payload,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": "PersonalAI/0.1.7",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code == 401:
                raise ToolError(
                    "Ollama rejected the API key (HTTP 401 Unauthorized). "
                    "Create a valid Ollama API key and run /websetup again."
                ) from e
            raise ToolError(
                f"Ollama web search HTTP {e.code}: {body[:300]}"
            ) from e
        except urllib.error.URLError as e:
            raise ToolError(f"Web search connection failed: {e}") from e

        if not isinstance(parsed, dict):
            raise ToolError("Ollama returned an unexpected web-search response.")
        return parsed

    def test_web_search_key(self, key: str) -> tuple[bool, str]:
        key = key.strip()
        if not key:
            return False, "No API key was provided."

        try:
            parsed = self._ollama_web_search_request(
                key=key,
                query="Ollama",
                max_results=1,
                timeout=30,
            )
        except ToolError as e:
            return False, str(e)

        results = parsed.get("results", [])
        if not isinstance(results, list):
            return False, "Ollama returned an unexpected response."
        return True, "Ollama web search connection verified."

    def test_saved_web_search(self) -> tuple[bool, str]:
        key = load_ollama_api_key(self.data_dir)
        if not key:
            return False, "No Ollama API key is configured. Run /websetup."
        return self.test_web_search_key(key)

    def web_search(self, query: str, max_results: int = 5):
        key = load_ollama_api_key(self.data_dir)
        if not key:
            raise ToolError("Web search is not configured. Run /websetup.")

        parsed = self._ollama_web_search_request(
            key=key,
            query=query,
            max_results=max_results,
        )

        results = parsed.get("results", [])
        cleaned = []
        for item in results[:max(1, min(10, int(max_results)))]:
            cleaned.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": str(item.get("content", ""))[:3000],
                }
            )
        return {"query": query.strip(), "results": cleaned}

    def web_fetch(
        self,
        url: str,
        *,
        timeout: int = 30,
        max_chars: int = 12000,
    ):
        url = url.strip()
        if not re.match(r"^https?://", url, flags=re.I):
            raise ToolError("Only HTTP and HTTPS URLs are allowed.")

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 PersonalAI/0.1.6"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(
                req, timeout=max(3, min(30, int(timeout)))
            ) as response:
                content_type = response.headers.get("Content-Type", "")
                raw = response.read(1_500_000)
        except urllib.error.HTTPError as e:
            raise ToolError(f"Webpage returned HTTP {e.code}.") from e
        except urllib.error.URLError as e:
            raise ToolError(f"Could not fetch webpage: {e}") from e

        if "text" not in content_type and "json" not in content_type:
            raise ToolError(f"Unsupported page content type: {content_type}")

        text = raw.decode("utf-8", errors="replace")
        if "html" in content_type.lower() or "<html" in text[:500].lower():
            parser = _TextExtractor()
            parser.feed(text)
            title = " ".join(parser.title_parts).strip()
            body = " ".join(parser.parts)
        else:
            title = ""
            body = text

        body = re.sub(r"\s+", " ", body).strip()
        return {
            "url": url,
            "title": title,
            "content": body[:max(500, min(50000, int(max_chars)))],
            "truncated": len(body) > max(500, min(50000, int(max_chars))),
        }

    def research_evidence(
        self,
        query: str,
        max_sources: int = 3,
    ) -> dict[str, Any]:
        query = " ".join(str(query).split())
        if not query:
            raise ToolError("Research query is empty.")

        max_sources = max(1, min(5, int(max_sources)))
        searches = [query]
        topic_terms = _topic_terms(query)
        variant = _research_query_variant(query)
        if variant.lower() != query.lower():
            searches.append(variant)

        candidates: dict[str, dict[str, Any]] = {}
        for search_index, search_query in enumerate(searches):
            result = self.web_search(search_query, max_results=8)
            for rank, item in enumerate(result.get("results", [])):
                url = str(item.get("url", "")).strip()
                if not url or url in candidates:
                    continue
                title = str(item.get("title", "")).strip()
                snippet = " ".join(str(item.get("content", "")).split())
                overlap = len(topic_terms & _topic_terms(f"{title} {snippet}"))
                if topic_terms and not overlap:
                    continue
                score, authority = _source_authority(url, title, snippet)
                base_authority = score
                score += max(0, 16 - rank * 2)
                if search_index == 0:
                    score += 3
                candidates[url] = {
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "score": score,
                    "authority": authority,
                    "topic_overlap": overlap,
                    "base_authority": base_authority,
                    "domain": _source_host(url),
                }

        ordered = sorted(
            candidates.values(),
            key=lambda item: (item["topic_overlap"], item["score"]),
            reverse=True,
        )
        ordered = _prefer_independent_candidates(ordered)

        sources = []
        fetched_sources = 0
        fetch_attempts = 0

        for item in ordered:
            if fetched_sources >= max_sources:
                break
            if fetch_attempts >= 6:
                break

            fetch_attempts += 1
            page = None
            try:
                page = self.web_fetch(
                    item["url"],
                    timeout=10,
                    max_chars=6000,
                )
            except Exception as e:
                self.logger.info(
                    "Research source fetch skipped | url=%s error=%r",
                    item["url"],
                    e,
                )

            page_content = (
                " ".join(str(page.get("content", "")).split())
                if page
                else ""
            )
            source_title = (
                str(page.get("title", "")).strip()
                if page
                else ""
            ) or item["title"]
            source_text = page_content or item["snippet"]
            # A relevant search snippet cannot make an unrelated fetched page
            # (for example a privacy notice) suitable evidence for the topic.
            if topic_terms and not topic_terms & _topic_terms(source_text):
                continue
            excerpt = extract_relevant_passage(source_text, query)
            if not excerpt:
                continue
            score, authority = _source_authority(
                item["url"], source_title, source_text
            )
            base_authority = score
            score += max(0, int(item["score"]) // 5)

            quote = (
                extract_exact_quote(
                    excerpt,
                    query,
                    max_words=24,
                )
                if page_content
                else ""
            )
            if quote and quote not in re.split(r"(?<=[.!?])\s+", page_content):
                # A bounded window can start inside a very long sentence.
                # Its fragment must never become a verified complete quote.
                quote = ""

            if authority.startswith("Low-priority"):
                continue

            source = {
                "id": 0,
                "title": source_title or item["url"],
                "url": item["url"],
                "domain": _source_host(item["url"]),
                "authority": authority,
                "authority_score": score,
                "base_authority": base_authority,
                "quote": quote,
                "excerpt": excerpt,
                "excerpt_truncated": excerpt != source_text,
                "topic_overlap": len(topic_terms & _topic_terms(excerpt)),
                "content_origin": "fetched_page" if page_content else "search_snippet",
                "page_fetched": bool(page_content),
                "quote_verified_from_fetched_page": bool(quote and page_content),
            }
            sources.append(source)
            if page_content:
                fetched_sources += 1

        # A short quotable sentence does not make a weaker source better than
        # a more relevant passage that needs its full qualification.
        sources.sort(key=lambda source: (source["topic_overlap"], source["page_fetched"], source["authority_score"]), reverse=True)
        sources = _prefer_independent_candidates(sources)[:max_sources]

        for index, source in enumerate(sources, start=1):
            source.pop("base_authority", None)
            source["id"] = index

        return {
            "query": query,
            "method": (
                "Ranked live-web research prioritising topic relevance, then government, academic, "
                "peer-reviewed, standards and official primary sources; comparable results prefer distinct hosts."
            ),
            "sources": sources,
            "source_count": len(sources),
            "quote_rule": (
                "Only quote text where quote_verified_from_fetched_page is true. "
                "Quotes are complete short verbatim sentences from the fetched page. "
                "Reading a page or verifying its wording does not verify every claim in an answer."
            ),
        }

    def workspace_list(self, path: str = "."):
        target = self._safe_workspace_path(path)
        if not target.exists():
            raise ToolError("Path does not exist.")
        if not target.is_dir():
            raise ToolError("Path is not a directory.")

        items = []
        for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            rel = child.relative_to(self.workspace)
            items.append(
                {
                    "path": str(rel).replace("\\", "/"),
                    "type": "directory" if child.is_dir() else "file",
                    "size": child.stat().st_size if child.is_file() else None,
                }
            )
        return items[:500]

    def workspace_read(self, path: str, max_chars: int = 20000):
        target = self._safe_workspace_path(path)
        if not target.is_file():
            raise ToolError("File does not exist.")
        if target.stat().st_size > 5_000_000:
            raise ToolError("File is too large for this text reader.")
        max_chars = max(500, min(100000, int(max_chars)))
        text = target.read_text(encoding="utf-8", errors="replace")
        return {
            "path": str(target.relative_to(self.workspace)).replace("\\", "/"),
            "content": text[:max_chars],
            "truncated": len(text) > max_chars,
        }

    def workspace_write(self, path: str, content: str):
        target = self._safe_workspace_path(path)
        if target == self.workspace:
            raise ToolError("A file path is required.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {
            "path": str(target.relative_to(self.workspace)).replace("\\", "/"),
            "chars_written": len(content),
        }
