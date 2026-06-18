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
MOJIBAKE_MARKERS = ("â", "ã", "Ã", "æ", "å", "ï", "Â")
TYPOGRAPHIC_TRANSLATION = str.maketrans(
    {
        "\u00a0": " ",
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u3010": "[",
        "\u3011": "]",
    }
)


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
    text = repair_mojibake(text)
    text = text.translate(TYPOGRAPHIC_TRANSLATION)
    text = replace_downloaded_language(text)
    text = (
        text.replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\\t", " ")
        .replace("\r", "\n")
        .replace("\t", " ")
    )
    text = re.sub(r"[\u25a1\u25aa\u25a0\u25cf\u2022\uf06f]\s*", "- ", text)
    text = re.sub(r"(?m)^\s*[\?\ufffd]\s+(?=[A-Z0-9])", "- ", text)
    text = re.sub(r"[ \f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.strip().splitlines()).strip()


def repair_mojibake(text: str) -> str:
    if not any(marker in text for marker in MOJIBAKE_MARKERS):
        return text
    try:
        repaired = text.encode("cp1252", errors="ignore").decode("utf-8", errors="ignore")
    except UnicodeError:
        return text
    original_markers = sum(text.count(marker) for marker in MOJIBAKE_MARKERS)
    repaired_markers = sum(repaired.count(marker) for marker in MOJIBAKE_MARKERS)
    if repaired and repaired_markers < original_markers and len(repaired) >= len(text) * 0.6:
        return repaired
    return text


def strip_cjk_text(text: str) -> str:
    text = re.sub(r"[\u3400-\u9fff]+", " ", text)
    text = re.sub(r"[\uff00-\uffef]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


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
    text = strip_cjk_text(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(re.findall(r"[A-Za-z0-9]", text)) < 20:
        return ""
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
    answer_part = format_answer_part_for_chat(answer_part)

    quote_lines, source_lines = compact_evidence_sections(
        evidence_part,
        max_quotes=max_quotes,
        max_sources=max_sources,
    )
    if source_lines == [NO_SOURCE_TEXT]:
        source_lines = []
    sections = [answer_part]
    if quote_lines:
        sections.append("Evidence:\n" + "\n".join(quote_lines))
    if source_lines:
        sections.append("Resources used:\n" + "\n".join(source_lines))
    return "\n\n".join(section for section in sections if section.strip())


def format_answer_part_for_chat(answer: str) -> str:
    text = clean_visible_text(answer)
    text = expand_inline_numbered_list(text)
    text = re.sub(r"(\[\d+\])\s+(?=[A-Z])", r"\1\n\n", text)
    text = strip_inline_citations_for_chat(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_inline_citations_for_chat(text: str) -> str:
    text = re.sub(r"\s*\[(?:\d+(?:,\s*)?)+\]", "", text)
    text = re.sub(r"\s+([.;,:])", r"\1", text)
    return text


def expand_inline_numbered_list(text: str) -> str:
    matches = list(re.finditer(r"\((\d+)\)\s+", text))
    if len(matches) < 2:
        return text

    prefix = text[: matches[0].start()].strip()
    if not prefix.endswith(":"):
        return text

    lines = [prefix]
    trailing_text = ""
    for idx, match in enumerate(matches):
        number = match.group(1)
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        item = text[start:end].strip()
        item = re.sub(r"^(and\s+)", "", item, flags=re.I).strip()
        if idx + 1 < len(matches):
            item = strip_inline_citations_for_chat(item)
            item = re.sub(r"(?:;|,)?\s+and\s*$", "", item, flags=re.I)
            item = item.rstrip(";,. ")
        else:
            citation_break = re.search(r"(\[\d+\])\s+(?=[A-Z])", item)
            if citation_break:
                trailing_text = item[citation_break.end() :].strip()
                item = item[: citation_break.end()].strip()
            item = strip_inline_citations_for_chat(item)
            item = item.rstrip("; ")
        if item:
            lines.append(f"{number}. {item}")

    if trailing_text:
        lines.extend(["", trailing_text])
    return "\n".join(lines)


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
            quote_line = format_chat_quote_line(quote)
            if quote_line:
                quote_lines.append(quote_line)
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
    source_lines = [f"- {label}" for label in source_order]
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
        "transcripts": "Video transcript",
    }.get(source.lower(), source.title() or "Source")
    display_path = path or public_ref
    return f"{source_name}: {display_path}"


def format_chat_quote_line(quote: str) -> str:
    cleaned = clean_chat_quote(quote)
    if not cleaned:
        return ""
    return f"- {quote_label(quote)}: \"{cleaned}\""


def quote_label(quote: str) -> str:
    lowered = quote.lower()
    if "try to bring less stuff" in lowered or "previous cohorts" in lowered:
        return "Packing advice"
    if "valid passport" in lowered and ("x1" in lowered or "jw202" in lowered or "admission notice" in lowered):
        return "Required packing items"
    if "passport" in lowered or "blank page" in lowered:
        return "Passport requirement"
    if "jw202" in lowered or "admission notice" in lowered or "university documents" in lowered:
        return "University documents"
    if "physical exam" in lowered or "blood test" in lowered:
        return "Physical exam"
    if "scanned copy" in lowered or "scanned copies" in lowered:
        return "Scanned copies"
    if "visa application form" in lowered:
        return "Visa application form"
    return "Source text"


def clean_chat_quote(text: str, max_chars: int = 115) -> str:
    quote = clean_evidence_quote(text, max_chars=260)
    quote = re.sub(r"^Step\s+\d+:\s+[A-Z0-9 ,/&()'-]+\s+-\s+", "", quote)
    quote = re.sub(r"^Step\s+\d+:\s+[A-Z0-9 ,/&()'-]+\s+1\.\s+", "", quote)
    quote = re.sub(r"\s+\d+\.\s+", "; ", quote)
    quote = re.sub(r"\s+-\s+", "; ", quote)
    quote = re.sub(r"\s+", " ", quote).strip()
    if len(quote) <= max_chars:
        return quote
    return quote[:max_chars].rsplit(" ", 1)[0].rstrip(".,;:") + "..."


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
