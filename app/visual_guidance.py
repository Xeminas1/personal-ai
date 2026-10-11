"""Image-first routing and grounded answer checks for attached visual tasks.

This never reads project source, grants new permissions, or sends attached
images to a new service. Actual screenshot observations still come from the
existing opt-in, paired-PC vision service.
"""
from __future__ import annotations

import json
import re
from typing import Any

# Remove negative SOURCE instructions before looking for affirmative code
# requests. "Do not inspect source code" is not a request to inspect it.
_NEGATIVE_SOURCE = re.compile(
    r"\b(?:do\s+not|don't|never|without|no)\s+"
    r"(?:perform\s+|attempt\s+|use\s+|(?:any\s+))?"
    r"(?:code\s+)?(?:inspect|read|trace|analyse|analyze|review|modify|edit|"
    r"search|browse|research|open|change)\b"
    r"[^\n.!?;]*",
    re.IGNORECASE,
)
_NEGATIVE_DEV_MODE = re.compile(
    r"\b(?:do\s+not|don't|never|without|no)\s+"
    r"(?:use|using)\s+(?:(?:the|your)\s+)?developer\s+mode\b"
    r"[^\n.!?;]*",
    re.IGNORECASE,
)
_AFFIRMATIVE_SOURCE = re.compile(
    r"\b(?:use|using|via|with)\s+(?:the\s+|your\s+)?developer\s+mode\b"
    r"|\b(?:inspect|read|trace|analyse|analyze|review|modify|edit|"
    r"fix|change|locate|find)\s+(?:(?:the|actual|relevant|local|my)\s+){0,3}"
    r"(?:kotlin|source\s+code|codebase|repository|repo\b|"
    r"source\s+files?|\.kt\b|files?\s+(?:and|that|responsible))"
    r"|\b(?:which|what)\s+(?:kotlin\s+)?(?:files?|functions?|classes?)\s+"
    r"(?:implement|control|should\s+change)\b",
    re.IGNORECASE,
)
_VISUAL_INTENT = re.compile(
    r"\b(?:image|images|picture|pictures|photo|photos|screenshot|screenshots|"
    r"concept|design|visual|visually|look|see|describe|compare|"
    r"glow|colours?|colors?|sidebar|highlight|focus|layout|spacing|"
    r"what\s+is\s+(?:visible|shown))\b",
    re.IGNORECASE,
)
_VISUAL_FAILURE = re.compile(
    r"\b(?:provided\s+(?:source\s+)?files?\s+(?:implement|define|contain)|"
    r"source\s+code\s+(?:shows|implements|defines)|"
    r"the\s+image\s+(?:file\s+)?(?:is\s+)?not\s+(?:directly\s+)?"
    r"(?:accessible|available)|"
    r"cannot\s+(?:access|see|analyse|analyze|view)\s+"
    r"(?:the\s+)?(?:image|images|screenshot)|"
    r"would\s+you\s+like\s+me\s+to\s+(?:inspect|examine|read))\b",
    re.IGNORECASE,
)
_CODE_RESULT = re.compile(
    r"\b(?:[A-Za-z_][A-Za-z_0-9]{1,80}\.(?:kt|kts|py|java|cs)|"
    r"ffmpeg|subprocess\.run|tempfile\.TemporaryDirectory|"
    r"test_artwork|ArtworkLoader|HomeFocusPolicy)\b",
    re.IGNORECASE,
)


def is_image_only_request(question: str, attachments: Any) -> bool:
    """Route only an actual image attachment and a visual-only request.

    Explicit positive source-code instructions still take the mixed
    screenshot+source workflow; negative instructions do not.
    """
    if not isinstance(attachments, list) or not attachments:
        return False
    images = [
        row for row in attachments if isinstance(row, dict)
        and (
            str(row.get("mime", "")).lower().startswith("image/")
            or str(row.get("name", "")).lower().endswith(
                (".png", ".jpeg", ".jpg", ".webp", ".xemai-video.json")
            )
            or str(row.get("mime", "")).lower() ==
            "application/vnd.xemai.video-frames+json"
        )
    ]
    if not images or len(images) != len(attachments):
        return False

    q = str(question or "")[:4000]
    if not _VISUAL_INTENT.search(q):
        return False
    positive = _NEGATIVE_SOURCE.sub("", _NEGATIVE_DEV_MODE.sub("", q))
    return not bool(_AFFIRMATIVE_SOURCE.search(positive))


def visual_reports_ready(attachments: list[dict], reports: dict[str, str]) -> bool:
    """An enabled vision service isn't proof this turn's images were seen."""
    if not attachments:
        return False
    return all(
        isinstance(item, dict)
        and isinstance(reports.get(str(item.get("path", "")).replace("\\", "/")), str)
        and "VISION MODEL OBSERVATIONS (" in reports[
            str(item.get("path", "")).replace("\\", "/")
        ]
        for item in attachments
    )


VISUAL_ONLY_INSTRUCTIONS = (
    "IMAGE-ONLY TASK. The user attached visual media and requested a visual "
    "description or comparison. Do not read source code, search the internet, "
    "offer code refactoring or discuss unrelated program files. Source/code "
    "discussion in conversation history is not evidence of what is in these "
    "images. Use ONLY the vision observations embedded in the current user "
    "attachment evidence; those observations are interpretations by the "
    "separate PC vision model, not direct pixel access by this chat model. "
    "Answer the requested description/comparison, naming the visible labels "
    "and concrete layout, colours, positions, focus and glow effects, "
    "distinguishing actual highlighted sidebar ROW from a highlighted poster "
    "in the content area. Don't infer the highlighted sidebar item from the "
    "currently visible Films shelf. For multiple images compare explicitly. "
    "If a detail isn't in the observations, label it uncertain rather than "
    "inventing it. Do not claim the attached image was unavailable when the "
    "PC vision observations are present. Finish the visual answer directly."
)


class NoExternalOrSourceTools:
    """Deny ALL model-chosen tool calls for an image-only task."""

    @staticmethod
    def definitions() -> list:
        return []

    @staticmethod
    def execute(name: str, arguments: Any) -> str:
        return json.dumps({
            "ok": False,
            "error": "No source or external tools are authorised for this image-only task.",
        })


def visual_answer_needs_retry(question: str, answer: str) -> bool:
    """Catch obvious task diversion, not subtle misreads of visual content."""
    a = str(answer or "").strip()
    if len(a) < 75 or _CODE_RESULT.search(a) or _VISUAL_FAILURE.search(a):
        return True
    q = str(question or "")
    if re.search(r"\b(?:sidebar|navigation)\b", q, re.IGNORECASE):
        if not re.search(r"\b(?:sidebar|navigation|home|films|search)\b", a, re.IGNORECASE):
            return True
    return False


def visual_unavailable_response() -> str:
    return (
        "I received your attached image(s), but the paired-PC vision service "
        "did not return usable observations for every attachment in this turn. "
        "I can't reliably describe or compare their visible contents. "
        "Check that the PC is awake, that PC visual analysis reports ready, "
        "and then retry with the images attached. "
        "I haven't searched the web or inspected unrelated source files."
    )


def visual_incomplete_response() -> str:
    return (
        "I received the visual analysis observations, but I couldn't generate "
        "a reliable answer to your screenshot request after a retry. "
        "I won't substitute unrelated source-code explanations or guesses "
        "about what is highlighted in the images. "
        "Please retry the images; the failure can be diagnosed from the "
        "visual-analysis and reply logs."
    )
