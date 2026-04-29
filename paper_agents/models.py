from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Paper:
    paper_id: str
    title: str
    authors: list[str]
    abstract: str
    published: str
    updated: str
    categories: list[str]
    source: str = "arxiv"
    abs_url: str = ""
    pdf_url: str = ""
    primary_category: str = ""
    semantic_tldr: str = ""
    citation_count: int | None = None
    venue: str = ""
    tags: list[str] = field(default_factory=list)
    relevance_score: float = 0.0
    priority: str = "skip"
    summary: str = ""
    reason: str = ""

    def text_for_matching(self) -> str:
        return f"{self.title}\n{self.abstract}".lower()
