from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .clients import ArxivClient, OpenAIClient, SemanticScholarClient
from .config import AppConfig
from .models import Paper


class CollectorAgent:
    """Collects recent papers from deterministic sources."""

    def __init__(self, config: AppConfig, arxiv: ArxivClient | None = None):
        self.config = config
        self.arxiv = arxiv or ArxivClient()

    def run(self, *, run_date: datetime, days: int | None = None) -> list[Paper]:
        end = run_date.astimezone(timezone.utc)
        start = end - timedelta(days=days or self.config.sources.lookback_days)
        return self.arxiv.search_recent(
            start=start,
            end=end,
            categories=self.config.sources.arxiv_categories,
            max_results_per_category=self.config.sources.max_results_per_category,
        )


class MetadataAgent:
    """Adds citation metadata and Semantic Scholar TLDR summaries when available."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.client = SemanticScholarClient(config.semantic_scholar.sleep_seconds)

    def run(self, papers: list[Paper]) -> list[Paper]:
        if not self.config.semantic_scholar.enabled:
            return papers
        return [self.client.enrich(paper) for paper in papers]


class ClassifierAgent:
    """Labels papers as VLA, CV, robot learning, multimodal, or irrelevant."""

    def __init__(self, config: AppConfig, llm: OpenAIClient | None = None):
        self.config = config
        self.llm = llm or OpenAIClient(config.llm.model, config.llm.provider)

    def run(self, papers: list[Paper]) -> list[Paper]:
        for paper in papers:
            self.classify(paper)
        return papers

    def classify(self, paper: Paper) -> Paper:
        if self.config.llm.enabled and self.llm.available:
            if self._classify_with_llm(paper):
                return paper
        return self._classify_with_rules(paper)

    def _classify_with_llm(self, paper: Paper) -> bool:
        system = (
            "你是一个论文筛选 Agent，专门判断论文是否属于 VLA、CV、Robot Learning、"
            "Embodied AI 或 Multimodal AI。只输出 JSON。"
        )
        user = f"""
请阅读标题和摘要，输出 JSON：
{{
  "tags": ["VLA" 或 "CV" 等标签],
  "relevance_score": 0 到 5 的数字,
  "priority": "must_read" | "read" | "skim" | "skip",
  "reason": "不超过 30 个中文字符的理由"
}}

标题：{paper.title}
分类：{", ".join(paper.categories)}
摘要：{paper.abstract}
""".strip()
        try:
            raw = self.llm.complete(system, user)
            parsed = _parse_json(raw)
        except Exception:
            return False

        paper.tags = [str(tag) for tag in parsed.get("tags", []) if str(tag).strip()]
        paper.relevance_score = float(parsed.get("relevance_score", 0))
        paper.priority = str(parsed.get("priority", "skip"))
        paper.reason = str(parsed.get("reason", ""))
        return True

    def _classify_with_rules(self, paper: Paper) -> Paper:
        text = paper.text_for_matching()
        tags: list[str] = []
        score = 0.0

        vla_hits = [keyword for keyword in self.config.sources.vla_keywords if keyword.lower() in text]
        cv_hits = [keyword for keyword in self.config.sources.cv_keywords if keyword.lower() in text]

        if vla_hits:
            tags.append("VLA")
            score += min(3.5, 1.5 + len(vla_hits) * 0.7)
        if cv_hits or "cs.CV" in paper.categories:
            tags.append("CV")
            score += min(2.0, 0.8 + len(cv_hits) * 0.3)
        if "cs.RO" in paper.categories or any(word in text for word in ["robot", "manipulation", "navigation"]):
            tags.append("Robot Learning")
            score += 1.0
        if any(word in text for word in ["vision-language", "multimodal", "vlm", "large language model"]):
            tags.append("Multimodal")
            score += 0.8

        paper.tags = sorted(set(tags))
        paper.relevance_score = min(5.0, score)
        if paper.relevance_score >= 4:
            paper.priority = "must_read"
        elif paper.relevance_score >= 2.5:
            paper.priority = "read"
        elif paper.relevance_score >= 1.2:
            paper.priority = "skim"
        else:
            paper.priority = "skip"
        paper.reason = "规则匹配：" + ("、".join(paper.tags) if paper.tags else "相关性低")
        return paper


class SummarizerAgent:
    """Creates one-sentence Chinese summaries."""

    def __init__(self, config: AppConfig, llm: OpenAIClient | None = None):
        self.config = config
        self.llm = llm or OpenAIClient(config.llm.model, config.llm.provider)

    def run(self, papers: list[Paper]) -> list[Paper]:
        for paper in papers:
            self.summarize(paper)
        return papers

    def summarize(self, paper: Paper) -> Paper:
        if self.config.llm.enabled and self.llm.available:
            if self._summarize_with_llm(paper):
                return paper
        if paper.semantic_tldr:
            paper.summary = paper.semantic_tldr
        else:
            paper.summary = f"本文围绕“{paper.title}”展开，主要贡献见摘要。"
        return paper

    def _summarize_with_llm(self, paper: Paper) -> bool:
        system = "你是论文摘要 Agent，擅长用中文一句话概括机器学习论文贡献。"
        user = f"""
请根据论文标题和摘要，用一句中文总结核心贡献。
要求：包含研究问题、主要方法、关键价值；不超过 60 个中文字符；不要换行。

标题：{paper.title}
已有 TLDR：{paper.semantic_tldr}
摘要：{paper.abstract}
""".strip()
        try:
            paper.summary = self.llm.complete(system, user).replace("\n", " ").strip()
        except Exception:
            return False
        return bool(paper.summary)


class CuratorAgent:
    """Ranks papers and removes irrelevant items for the daily report."""

    def __init__(self, config: AppConfig):
        self.config = config

    def run(self, papers: list[Paper]) -> list[Paper]:
        selected = papers
        if not self.config.publisher.include_irrelevant:
            selected = [paper for paper in papers if paper.priority != "skip"]
        selected.sort(key=lambda paper: (paper.relevance_score, paper.citation_count or 0, paper.updated), reverse=True)
        return selected[: self.config.publisher.top_k]


class PublisherAgent:
    """Writes the daily Markdown report."""

    def __init__(self, config: AppConfig):
        self.config = config

    def run(self, papers: list[Paper], *, run_date: datetime) -> Path:
        output_dir = Path(self.config.publisher.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{run_date.date().isoformat()}.md"
        path.write_text(self._render_markdown(papers, run_date), encoding="utf-8")
        return path

    def _render_markdown(self, papers: list[Paper], run_date: datetime) -> str:
        lines = [
            f"# VLA & CV Daily Papers - {run_date.date().isoformat()}",
            "",
            f"- 生成时间：{run_date.isoformat(timespec='seconds')}",
            f"- 收录论文：{len(papers)} 篇",
            "",
        ]
        groups = [
            ("必读", [paper for paper in papers if paper.priority == "must_read"]),
            ("值得读", [paper for paper in papers if paper.priority == "read"]),
            ("快速浏览", [paper for paper in papers if paper.priority == "skim"]),
        ]
        for heading, group in groups:
            if not group:
                continue
            lines.extend([f"## {heading}", ""])
            for paper in group:
                authors = ", ".join(paper.authors[:4])
                if len(paper.authors) > 4:
                    authors += " et al."
                lines.extend(
                    [
                        f"### {paper.title}",
                        f"- 标签：{', '.join(paper.tags) or '未分类'}",
                        f"- 分数：{paper.relevance_score:.1f}/5；理由：{paper.reason}",
                        f"- 一句话总结：{paper.summary}",
                        f"- 作者：{authors or '未知'}",
                        f"- 分类：{', '.join(paper.categories)}",
                        f"- 链接：[{paper.paper_id}]({paper.abs_url})；[PDF]({paper.pdf_url})",
                        "",
                    ]
                )
        if not papers:
            lines.append("今天没有筛到符合条件的论文。")
            lines.append("")
        return "\n".join(lines)


class WorkflowAgent:
    """Orchestrates the full daily paper workflow."""

    def __init__(self, config: AppConfig):
        self.collector = CollectorAgent(config)
        self.metadata = MetadataAgent(config)
        self.classifier = ClassifierAgent(config)
        self.summarizer = SummarizerAgent(config)
        self.curator = CuratorAgent(config)
        self.publisher = PublisherAgent(config)

    def run(self, *, run_date: datetime, days: int | None = None) -> tuple[list[Paper], list[Paper], Path]:
        papers = self.collector.run(run_date=run_date, days=days)
        papers = self.metadata.run(papers)
        papers = self.classifier.run(papers)
        papers = self.summarizer.run(papers)
        selected = self.curator.run(papers)
        report = self.publisher.run(selected, run_date=run_date)
        return papers, selected, report


def papers_to_jsonable(papers: list[Paper]) -> list[dict]:
    return [asdict(paper) for paper in papers]


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.removeprefix("json").strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end >= start:
        raw = raw[start : end + 1]
    return json.loads(raw)
