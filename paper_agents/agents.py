from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .clients import ArxivClient, FeishuClient, OpenAIClient, SemanticScholarClient
from .config import AppConfig
from .models import Paper


class CollectorAgent:
    """Collects recent papers from deterministic sources."""

    def __init__(self, config: AppConfig, arxiv: ArxivClient | None = None):
        self.config = config
        self.arxiv = arxiv or ArxivClient()

    def run(self, *, run_date: datetime, days: int | None = None, start_date: datetime | None = None) -> list[Paper]:
        end = run_date.astimezone(timezone.utc)
        start = start_date.astimezone(timezone.utc) if start_date else end - timedelta(days=days or self.config.sources.lookback_days)
        print(f"Collecting arXiv papers from {start.isoformat()} to {end.isoformat()}")
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
            "Embodied AI、Multimodal AI 或 World Model。只输出 JSON。"
        )
        user = f"""
请阅读标题和摘要，输出 JSON：
{{
  "tags": ["VLA"、"CV"、"World Model" 等标签],
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
        world_model_hits = [keyword for keyword in self.config.sources.world_model_keywords if keyword.lower() in text]

        if vla_hits:
            tags.append("VLA")
            score += min(3.5, 1.5 + len(vla_hits) * 0.7)
        if world_model_hits:
            tags.append("World Model")
            score += min(3.3, 1.4 + len(world_model_hits) * 0.6)
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
            paper.summary = self._compact_summary(paper.semantic_tldr)
        else:
            paper.summary = self._fallback_summary(paper)
        return paper

    def _summarize_with_llm(self, paper: Paper) -> bool:
        system = (
            "你是机器学习论文快报编辑。你只输出一句中文短句，"
            "准确、具体、信息密度高，不写客套话。"
        )
        user = f"""
请为下面论文写一句中文总结。

硬性要求：
- 只输出一句话，不要编号、不要解释、不要换行
- 35 到 55 个中文字符左右
- 必须包含“解决什么问题 + 用什么方法/系统 + 带来什么价值”
- 禁止写“本文围绕”“主要贡献见摘要”“提出了一种方法”等空泛句
- 不要机械复述标题；如果是 survey/tool/dataset/simulator，请直接说明用途

标题：{paper.title}
标签：{", ".join(paper.tags)}
已有 TLDR：{paper.semantic_tldr}
摘要：{paper.abstract}
""".strip()
        try:
            paper.summary = self._compact_summary(self.llm.complete(system, user))
        except Exception as error:
            print(f"Warning: LLM summary failed for {paper.paper_id}: {error}", file=sys.stderr)
            return False
        return bool(paper.summary)

    def _compact_summary(self, text: str) -> str:
        text = re.sub(r"\s+", " ", text).strip()
        text = text.strip("` \n\r\t")
        text = re.sub(r"^[\\-\\d\\.、）\\)\\s]+", "", text)
        if "\n" in text:
            text = text.splitlines()[0].strip()
        for delimiter in ["。", "！", "？"]:
            if delimiter in text:
                return text.split(delimiter)[0].strip() + delimiter
        return text[:90].strip()

    def _fallback_summary(self, paper: Paper) -> str:
        abstract = re.sub(r"\s+", " ", paper.abstract).strip()
        if abstract:
            first_sentence = re.split(r"(?<=[.!?])\\s+", abstract)[0].strip()
            if len(first_sentence) > 180:
                first_sentence = first_sentence[:177].rstrip() + "..."
            return f"摘要要点：{first_sentence}"
        return f"待总结：{paper.title}"


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


class NotifierAgent:
    """Sends the selected daily papers to Feishu."""

    def __init__(self, config: AppConfig, client: FeishuClient | None = None):
        self.config = config
        self.webhook_url = os.environ.get("FEISHU_WEBHOOK_URL", "")
        self.client = client or FeishuClient(
            webhook_url=self.webhook_url,
            secret=os.environ.get("FEISHU_SECRET", ""),
        )

    def available(self) -> bool:
        return bool(self.webhook_url)

    def run(self, papers: list[Paper], *, run_date: datetime, report: Path | None = None) -> bool:
        if not self.available():
            print("Feishu notification skipped: FEISHU_WEBHOOK_URL is not configured.", file=sys.stderr)
            return False
        self.client.send_text(self._render_text(papers, run_date, report))
        print("Feishu notification sent.", file=sys.stderr)
        return True

    def _render_text(self, papers: list[Paper], run_date: datetime, report: Path | None) -> str:
        lines = [
            f"论文日报 | VLA / CV / World Model | {run_date.date().isoformat()}",
            f"今日精选 {len(papers)} 篇",
            "",
        ]
        for index, paper in enumerate(papers, start=1):
            tags = ", ".join(paper.tags) or "未分类"
            lines.extend(
                [
                    f"{index}. {paper.title}",
                    f"标签：{tags} | 分数：{paper.relevance_score:.1f}/5",
                    f"一句话总结：{paper.summary}",
                    f"链接：{paper.abs_url}",
                    "",
                ]
            )
        if not papers:
            lines.append("今天没有筛到符合条件的论文。")
        if report:
            lines.append(f"完整日报已生成：{report}")
        return "\n".join(lines).strip()


class WorkflowAgent:
    """Orchestrates the full daily paper workflow."""

    def __init__(self, config: AppConfig):
        self.collector = CollectorAgent(config)
        self.metadata = MetadataAgent(config)
        self.classifier = ClassifierAgent(config)
        self.summarizer = SummarizerAgent(config)
        self.curator = CuratorAgent(config)
        self.publisher = PublisherAgent(config)
        self.notifier = NotifierAgent(config)

    def run(
        self,
        *,
        run_date: datetime,
        days: int | None = None,
        start_date: datetime | None = None,
        notify_feishu: bool = False,
    ) -> tuple[list[Paper], list[Paper], Path]:
        papers = self.collector.run(run_date=run_date, days=days, start_date=start_date)
        papers = self.metadata.run(papers)
        papers = self.classifier.run(papers)
        papers = self.summarizer.run(papers)
        selected = self.curator.run(papers)
        report = self.publisher.run(selected, run_date=run_date)
        if notify_feishu:
            self.notifier.run(selected, run_date=run_date, report=report)
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
