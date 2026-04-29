from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SourceConfig:
    arxiv_categories: list[str] = field(default_factory=lambda: ["cs.CV", "cs.RO", "cs.AI", "cs.LG"])
    lookback_days: int = 2
    max_results_per_category: int = 50
    vla_keywords: list[str] = field(default_factory=list)
    cv_keywords: list[str] = field(default_factory=list)


@dataclass
class SemanticScholarConfig:
    enabled: bool = True
    sleep_seconds: float = 1.0


@dataclass
class LLMConfig:
    enabled: bool = True
    provider: str = "openai"
    model: str = "gpt-4.1-mini"


@dataclass
class PublisherConfig:
    output_dir: str = "daily_papers"
    top_k: int = 12
    include_irrelevant: bool = False


@dataclass
class DatabaseConfig:
    path: str = "papers.db"


@dataclass
class AppConfig:
    sources: SourceConfig = field(default_factory=SourceConfig)
    semantic_scholar: SemanticScholarConfig = field(default_factory=SemanticScholarConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    publisher: PublisherConfig = field(default_factory=PublisherConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    return value if isinstance(value, dict) else {}


def load_config(path: str | Path | None) -> AppConfig:
    if path is None:
        return AppConfig()

    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    return AppConfig(
        sources=SourceConfig(**_section(raw, "sources")),
        semantic_scholar=SemanticScholarConfig(**_section(raw, "semantic_scholar")),
        llm=LLMConfig(**_section(raw, "llm")),
        publisher=PublisherConfig(**_section(raw, "publisher")),
        database=DatabaseConfig(**_section(raw, "database")),
    )
