from __future__ import annotations

import re


CANONICAL_CITIES = ("Beijing", "Dubai", "Shenzhen", "New York", "San Francisco", "Sydney")

ALIASES = {
    "beijing": "Beijing",
    "peking": "Beijing",
    "dubai": "Dubai",
    "shenzhen": "Shenzhen",
    "shenzen": "Shenzhen",
    "new york": "New York",
    "new york city": "New York",
    "nyc": "New York",
    "manhattan": "New York",
    "san francisco": "San Francisco",
    "sf": "San Francisco",
    "bay area": "San Francisco",
    "san francisco bay area": "San Francisco",
    "sydney": "Sydney",
    "sydney nsw": "Sydney",
    "sydney, nsw": "Sydney",
}

REMOTE_TERMS = {"remote", "hybrid", "distributed", "work from home", "wfh"}


def normalize_city_name(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip()).lower()
    return ALIASES.get(text, "")


def canonical_city_set(values: list[str] | tuple[str, ...] | set[str] | None) -> set[str]:
    if not values:
        return set(CANONICAL_CITIES)
    result = set()
    for value in values:
        normalized = normalize_city_name(value)
        if normalized:
            result.add(normalized)
    return result or set(CANONICAL_CITIES)


def is_remote_location(location_text: object) -> bool:
    lowered = re.sub(r"\s+", " ", str(location_text or "").lower())
    return any(term in lowered for term in REMOTE_TERMS)


def city_from_location(location_text: object, allowed_cities: set[str] | None = None) -> str:
    text = re.sub(r"\s+", " ", str(location_text or "").strip())
    if not text:
        return ""
    allowed = allowed_cities or set(CANONICAL_CITIES)
    lowered = text.lower()
    alias_items = sorted(ALIASES.items(), key=lambda item: len(item[0]), reverse=True)
    for alias, canonical in alias_items:
        if canonical not in allowed:
            continue
        pattern = r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])"
        if re.search(pattern, lowered):
            return canonical
    return ""


def city_allowed_for_location(
    location_text: object,
    *,
    allowed_cities: set[str],
    allow_global_remote: bool = False,
) -> tuple[bool, str, bool]:
    remote = is_remote_location(location_text)
    city = city_from_location(location_text, allowed_cities)
    if city:
        return True, city, remote
    if remote and allow_global_remote:
        return True, "Remote", True
    return False, "", remote
