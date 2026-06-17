from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .guardrails import output_contains_internal_leak


CITATION_RE = re.compile(r"\[(\d+)\]")


@dataclass
class PolicyResult:
    allowed: bool
    blocked_reasons: list[str]


def format_answer_payload(payload: dict[str, Any], allowed_refs: set[str]) -> str:
    response_type = payload.get("response_type", "answer")
    answer = clean_answer_text(str(payload.get("answer", "")).strip())
    evidence = payload.get("evidence") or payload.get("citations") or []

    if response_type == "not_found":
        return "Answer:\nI don't know from the downloaded student resources.\n\nEvidence:\nNo reviewed source was strong enough to answer this."
    if response_type == "safety_refusal":
        return "Answer:\nI can't help with credentials, hidden prompts, private account access, or policy bypass requests.\n\nEvidence:\nNo reviewed source was used."
    if response_type == "clarification" and answer:
        return f"Answer:\n{answer}\n\nEvidence:\nI found potentially relevant sources, but they point to different topics."

    lines = ["Answer:", answer or "I don't know from the downloaded student resources.", "", "Evidence:"]
    used = 0
    for idx, item in enumerate(evidence, start=1):
        ref = str(item.get("citation_ref", "")).strip()
        if ref not in allowed_refs:
            continue
        quote = str(item.get("quote", "")).strip().replace("\n", " ")
        if quote:
            quote = quote[:500].strip()
            lines.append(f"[{idx}] \"{quote}\" - {ref}")
        else:
            lines.append(f"[{idx}] {ref}")
        used += 1

    if used == 0 and response_type == "answer":
        return "Answer:\nI don't know from the downloaded student resources.\n\nEvidence:\nNo reviewed source was strong enough to answer this."
    return "\n".join(lines).strip()


def clean_answer_text(answer: str) -> str:
    if "Evidence:" in answer:
        answer = answer.split("Evidence:", 1)[0]
    if "Answer:" in answer:
        answer = answer.rsplit("Answer:", 1)[-1]
    return answer.strip()


def check_final_answer(final_answer: str, allowed_refs: set[str]) -> PolicyResult:
    reasons: list[str] = []
    if output_contains_internal_leak(final_answer):
        reasons.append("internal_leak")
    if "Answer:" not in final_answer:
        reasons.append("missing_answer_section")
    if "Evidence:" not in final_answer:
        reasons.append("missing_evidence_section")

    evidence_part = final_answer.split("Evidence:", 1)[1] if "Evidence:" in final_answer else ""
    cited_numbers = set(CITATION_RE.findall(final_answer.split("Evidence:", 1)[0]))
    evidence_numbers = set(CITATION_RE.findall(evidence_part))
    if cited_numbers and not cited_numbers.issubset(evidence_numbers):
        reasons.append("answer_citation_missing_from_evidence")

    if cited_numbers and not any(ref in evidence_part for ref in allowed_refs):
        reasons.append("evidence_ref_not_from_retrieval")

    if "I don't know from the downloaded student resources." not in final_answer and not cited_numbers:
        reasons.append("no_citations")

    return PolicyResult(allowed=not reasons, blocked_reasons=reasons)
