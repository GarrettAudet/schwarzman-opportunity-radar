from __future__ import annotations

import re
from dataclasses import dataclass


MAX_INPUT_CHARS = 2000

PROMPT_INJECTION_PHRASES = [
    "ignore previous instructions",
    "ignore all previous instructions",
    "ignore prior instructions",
    "reveal your system prompt",
    "show your system prompt",
    "developer message",
    "system message",
    "jailbreak",
    "bypass policy",
    "no citations",
    "answer without citations",
    "use unreviewed files",
    "print hidden",
    "hidden prompt",
    "tool output",
    "cite nothing",
    "pretend the source says",
]

HIGH_RISK_PROMPT_PHRASES = [
    "reveal your system prompt",
    "show your system prompt",
    "developer message",
    "system message",
    "print hidden",
    "hidden prompt",
    "tool output",
    "jailbreak",
    "bypass policy",
]

PRIVATE_ACTION_PHRASES = [
    "log into",
    "login to",
    "sign into",
    "use my password",
    "submit my",
    "apply for me",
    "check my account",
    "student id number",
]

RESOURCE_HINTS = [
    "blackboard",
    "career",
    "cover letter",
    "dress code",
    "gre",
    "gmat",
    "internship",
    "interview",
    "packing",
    "rencai",
    "resource",
    "resume",
    "transcript",
    "visa",
    "wechat",
    "x1",
]

SENSITIVE_PATTERNS = [
    re.compile(r"\b(passport|student id|government id|mfa|one[- ]?time code|password)\b", re.I),
    re.compile(r"\b[A-Z][0-9]{8}\b"),
    re.compile(r"\b\d{3}[- ]?\d{2}[- ]?\d{4}\b"),
]


@dataclass
class GuardrailResult:
    normalized_text: str
    prompt_injection_score: float
    suspicious_phrases: list[str]
    sensitive_data_detected: bool
    blocked: bool
    block_reason: str


def normalize_user_input(text: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_INPUT_CHARS]


def classify_user_input(text: str) -> GuardrailResult:
    normalized = normalize_user_input(text)
    lowered = normalized.lower()
    phrases = [phrase for phrase in PROMPT_INJECTION_PHRASES if phrase in lowered]
    sensitive = any(pattern.search(normalized) for pattern in SENSITIVE_PATTERNS)
    high_risk_prompt = any(phrase in lowered for phrase in HIGH_RISK_PROMPT_PHRASES)
    private_action = any(phrase in lowered for phrase in PRIVATE_ACTION_PHRASES)
    has_resource_hint = any(hint in lowered for hint in RESOURCE_HINTS)

    phrase_score = min(1.0, len(phrases) / 3)
    structure_score = 0.25 if "```" in normalized or "<system" in lowered else 0.0
    prompt_injection_score = min(1.0, phrase_score + structure_score)

    attack_dominated = prompt_injection_score >= 0.8 and len(normalized.split()) < 80
    fabrication_request = "pretend the source says" in lowered or "cite nothing" in lowered
    sensitive_private_request = bool(
        re.search(r"\b(student id|password|mfa|one[- ]?time code|government id)\b", lowered)
    )

    blocked = False
    reason = ""
    if private_action or sensitive_private_request:
        blocked = True
        reason = "private_or_delegated_action"
    elif high_risk_prompt and not has_resource_hint:
        blocked = True
        reason = "prompt_injection"
    elif fabrication_request and "?" not in normalized:
        blocked = True
        reason = "source_fabrication_request"
    elif attack_dominated and not has_resource_hint:
        blocked = True
        reason = "prompt_injection"
    elif sensitive:
        reason = "sensitive_data_detected"

    return GuardrailResult(
        normalized_text=normalized,
        prompt_injection_score=prompt_injection_score,
        suspicious_phrases=phrases,
        sensitive_data_detected=sensitive,
        blocked=blocked,
        block_reason=reason,
    )


def output_contains_internal_leak(text: str) -> bool:
    lowered = text.lower()
    leak_terms = [
        "system prompt",
        "developer message",
        "openrouter_api_key",
        "api key",
        "hidden policy",
        "tool output",
        "internal schema",
    ]
    return any(term in lowered for term in leak_terms)
