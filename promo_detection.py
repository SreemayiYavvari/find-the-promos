from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


_PROMO_PATTERNS: tuple[tuple[str, float], ...] = (
    (r"\b(buy now|shop now|order now|get yours)\b", 0.35),
    (r"\b(limited time|today only|while supplies last)\b", 0.28),
    (r"\b(discount|deal|offer|save \d+%|promo)\b", 0.22),
    (r"\b(use code|coupon|checkout)\b", 0.2),
    (r"\$\d+(?:\.\d{2})?", 0.18),
)

_MICRODRAMA_PATTERNS: tuple[tuple[str, float], ...] = (
    (r"\b(conflict|problem|struggle|can't|won't)\b", 0.08),
    (r"\b(solution|finally|resolved|works)\b", 0.1),
    (r"\b(hero|friend|family|mentor|customer)\b", 0.07),
    (r"\b(tonight|morning|late|suddenly)\b", 0.05),
)


@dataclass(frozen=True)
class PromoMatch:
    segment: str
    score: float
    reasons: tuple[str, ...]


def _split_segments(screenplay_text: str) -> list[str]:
    text = screenplay_text.strip()
    if not text:
        return []

    headings = list(
        re.finditer(
            r"(?m)^\s*(?:INT\.|EXT\.|INT/EXT\.|SCENE\s+\d+)",
            text,
        )
    )
    if not headings:
        return [text]

    segments: list[str] = []
    for i, heading in enumerate(headings):
        start = heading.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        segment = text[start:end].strip()
        if segment:
            segments.append(segment)
    return segments


def _score_with_patterns(text: str, patterns: Iterable[tuple[str, float]]) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    for pattern, weight in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            score += weight
            reasons.append(pattern)
    return score, reasons


def detect_and_rank_promos(screenplay_text: str, top_k: int | None = None) -> list[PromoMatch]:
    """
    Detect and rank likely promotional screenplay segments.

    The ranking score combines direct promo cues and microdrama storytelling cues.
    Scores are normalized to [0, 1].
    """
    segments = _split_segments(screenplay_text)
    ranked: list[PromoMatch] = []

    for segment in segments:
        promo_score, promo_reasons = _score_with_patterns(segment, _PROMO_PATTERNS)
        if promo_score == 0:
            continue

        drama_score, drama_reasons = _score_with_patterns(segment, _MICRODRAMA_PATTERNS)
        raw_score = promo_score + drama_score
        normalized = min(1.0, round(raw_score, 4))
        ranked.append(
            PromoMatch(
                segment=segment,
                score=normalized,
                reasons=tuple(promo_reasons + drama_reasons),
            )
        )

    ranked.sort(key=lambda match: match.score, reverse=True)
    if top_k is not None:
        return ranked[: max(0, top_k)]
    return ranked
