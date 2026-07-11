"""Extraction schemas for Semantic Memory (ADR 0010).

PractitionerProfile is a single, evolving profile of preferences; RecurringTopic is
one item in a growing collection of research subjects. Field descriptions steer the
extractor toward durable facts and away from confidential client/matter details,
which must never enter durable memory.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class PractitionerProfile(BaseModel):
    """Durable, non-confidential preferences — never a record of a client or matter."""

    background: Optional[str] = Field(
        default=None,
        description="The practitioner's own professional background, role, or goal when "
        "they state it about themselves (e.g. 'software engineer exploring legal tech', "
        "'in-house counsel', 'law student'). This is the USER's own identity — helpful "
        "for framing replies — never a client's, counterparty's, or any third party's. "
        "Exclude sensitive personal life (health, family, finances, religion).",
    )
    response_language: Optional[Literal["en", "bm", "mixed"]] = Field(
        default=None,
        description="Preferred response language, set only when expressed or clearly signalled.",
    )
    citation_style: Optional[str] = Field(
        default=None,
        description="How the practitioner wants answers presented, set when they direct "
        "the response format or style — brevity vs detail, bulleted vs prose, leading "
        "with section numbers, use of headings (e.g. 'prefers brief, bulleted answers'). "
        "Covers citation style too, but is not limited to citations.",
    )
    practice_areas: list[str] = Field(
        default_factory=list,
        description="General areas of law they focus on (e.g. 'employment') — never a specific matter.",
    )
    frequent_acts: list[str] = Field(
        default_factory=list,
        description="Malaysian Acts referenced frequently (e.g. 'Employment Act 1955').",
    )


class RecurringTopic(BaseModel):
    """A research subject the practitioner returns to — general, not a specific case."""

    topic: str = Field(
        description="A generalised research subject (e.g. 'unfair dismissal remedies'), "
        "stripped of client names, party names, or matter-specific details.",
    )
