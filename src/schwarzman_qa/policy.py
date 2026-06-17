from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .citations import public_citation_ref
from .guardrails import output_contains_internal_leak


CITATION_RE = re.compile(r"\[(\d+)\]")
NOT_FOUND_TEXT = "I don't know from the available resources."
NO_SOURCE_TEXT = "No reviewed source was strong enough to answer this."
OUT_OF_SCOPE_TEXT = "That is beyond my scope. I can only answer Schwarzman/Tsinghua questions using the available resources."


@dataclass
class PolicyResult:
    allowed: bool
    blocked_reasons: list[str]


def format_answer_payload(payload: dict[str, Any], allowed_refs: set[str]) -> str:
    allowed_refs = {public_citation_ref(ref) for ref in allowed_refs}
    response_type = payload.get("response_type", "answer")
    answer = clean_visible_text(clean_answer_text(str(payload.get("answer", "")).strip()))
    evidence = payload.get("evidence") or payload.get("citations") or []

    if response_type == "not_found":
        return f"Answer:\n{NOT_FOUND_TEXT}\n\nEvidence:\n{NO_SOURCE_TEXT}"
    if response_type == "out_of_scope":
        return f"Answer:\n{OUT_OF_SCOPE_TEXT}\n\nEvidence:\n{NO_SOURCE_TEXT}"
    if response_type == "safety_refusal":
        return "Answer:\nI can't help with credentials, hidden prompts, private account access, or policy bypass requests.\n\nEvidence:\nNo reviewed source was used."
    if response_type == "clarification" and answer:
        return f"Answer:\n{answer}\n\nEvidence:\nI found potentially relevant sources, but they point to different topics."

    lines = ["Answer:", answer or NOT_FOUND_TEXT, "", "Evidence:"]
    used = 0
    for idx, item in enumerate(evidence, start=1):
        ref = public_citation_ref(item.get("citation_ref", ""))
        if ref not in allowed_refs:
            continue
        quote = clean_evidence_quote(str(item.get("quote", "")), max_chars=260)
        if quote:
            lines.append(f"[{idx}] \"{quote}\" - {ref}")
        else:
            lines.append(f"[{idx}] {ref}")
        used += 1

    if used == 0 and response_type == "answer":
        return f"Answer:\n{NOT_FOUND_TEXT}\n\nEvidence:\n{NO_SOURCE_TEXT}"
    return clean_visible_text("\n".join(lines).strip())


def clean_answer_text(answer: str) -> str:
    if "Evidence:" in answer:
        answer = answer.split("Evidence:", 1)[0]
    if "Answer:" in answer:
        answer = answer.rsplit("Answer:", 1)[-1]
    return answer.strip()


def clean_visible_text(text: str) -> str:
    text = replace_downloaded_language(text)
    text = (
        text.replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\\t", " ")
        .replace("\r", "\n")
        .replace("\t", " ")
    )
    text = re.sub(r"[\u25aa\u25a0\u25cf\u2022]\s*", "- ", text)
    text = re.sub(r"(?m)^\s*[\?\ufffd]\s+(?=[A-Z0-9])", "- ", text)
    text = re.sub(r"[ \f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.strip().splitlines()).strip()


def replace_downloaded_language(text: str) -> str:
    replacements = [
        (r"\bdownloaded student resources\b", "available resources"),
        (r"\bdownloaded resources\b", "available resources"),
        (r"\bdownloaded corpus\b", "available resources"),
        (r"\breviewed downloaded corpus\b", "reviewed available resources"),
        (r"\bdownloaded resource\b", "available resource"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.I)
    return text


def clean_evidence_quote(text: str, max_chars: int = 220) -> str:
    text = clean_visible_text(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0].rstrip(".,;:") + "..."


def format_chat_answer(final_answer: str, max_quotes: int = 2, max_sources: int = 3) -> str:
    text = clean_visible_text(final_answer)
    answer_part = text
    evidence_part = ""
    if "Evidence:" in text:
        answer_part, evidence_part = text.split("Evidence:", 1)
    answer_part = clean_answer_text(answer_part)
    answer_part = clean_visible_text(answer_part)

    quote_lines, source_lines = compact_evidence_sections(
        evidence_part,
        max_quotes=max_quotes,
        max_sources=max_sources,
    )
    if source_lines == [NO_SOURCE_TEXT]:
        source_lines = []
    sections = [answer_part]
    if quote_lines:
        sections.append("Direct quotes:\n" + "\n".join(quote_lines))
    if source_lines:
        sections.append("Sources:\n" + "\n".join(source_lines))
    return "\n\n".join(section for section in sections if section.strip())


def compact_evidence_sections(
    evidence_part: str,
    max_quotes: int = 2,
    max_sources: int = 3,
) -> tuple[list[str], list[str]]:
    quote_lines: list[str] = []
    source_order: list[str] = []
    source_numbers: dict[str, list[str]] = {}
    evidence_text = clean_visible_text(evidence_part)
    if evidence_text == NO_SOURCE_TEXT or evidence_text.startswith("No reviewed source"):
        return [], [NO_SOURCE_TEXT]

    def add_source(number: str, label: str) -> None:
        if label not in source_numbers:
            if len(source_order) >= max_sources:
                return
            source_order.append(label)
            source_numbers[label] = []
        if number not in source_numbers[label]:
            source_numbers[label].append(number)

    matched_numbers: set[str] = set()
    for match in re.finditer(r"\[(\d+)\]\s+\"(.*?)\"\s+-\s+([^\n]+)", evidence_text, flags=re.S):
        number, quote, ref = match.groups()
        matched_numbers.add(number)
        label = source_label(ref)
        if len(quote_lines) < max_quotes:
            quote_lines.append(f"[{number}] \"{clean_evidence_quote(quote, max_chars=180)}\"")
        add_source(number, label)
        if len(source_order) >= max_sources and len(quote_lines) >= max_quotes:
            break

    for raw_line in evidence_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == NO_SOURCE_TEXT or line.startswith("No reviewed source"):
            return [], [NO_SOURCE_TEXT]

        quote_match = re.match(r"^\[(\d+)\]\s+\"", line)
        if quote_match and quote_match.group(1) in matched_numbers:
            continue

        number_match = re.match(r"^\[(\d+)\]\s+(.+)$", line)
        if number_match:
            number, ref = number_match.groups()
            if number in matched_numbers:
                continue
            label = source_label(ref)
            add_source(number, label)
        if len(source_order) >= max_sources and len(quote_lines) >= max_quotes:
            break
    source_lines = [
        f"{', '.join(f'[{number}]' for number in source_numbers[label])} {label}"
        for label in source_order
    ]
    return quote_lines, source_lines


def compact_source_lines(evidence_part: str, max_sources: int = 3) -> list[str]:
    _quote_lines, source_lines = compact_evidence_sections(evidence_part, max_quotes=0, max_sources=max_sources)
    return source_lines


def source_label(ref: str) -> str:
    public_ref = public_citation_ref(ref)
    source, _, path = public_ref.partition("/")
    source_name = {
        "blackboard": "Blackboard",
        "rencai": "Rencai",
        "transcripts": "Transcript",
    }.get(source.lower(), source.title() or "Source")
    display_path = path or public_ref
    return f"{source_name} - {display_path}"


def check_final_answer(final_answer: str, allowed_refs: set[str]) -> PolicyResult:
    allowed_refs = {public_citation_ref(ref) for ref in allowed_refs}
    final_answer = clean_visible_text(final_answer)
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

    no_citation_allowed = NOT_FOUND_TEXT in final_answer or OUT_OF_SCOPE_TEXT in final_answer
    if not no_citation_allowed and not cited_numbers:
        reasons.append("no_citations")

    return PolicyResult(allowed=not reasons, blocked_reasons=reasons)
