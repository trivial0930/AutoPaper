from __future__ import annotations

import unittest

from datetime import datetime, timezone
from unittest.mock import patch

from paper_agents.__main__ import _last_sunday_start
from paper_agents.agents import ClassifierAgent, CuratorAgent, NotifierAgent, SummarizerAgent
from paper_agents.clients import OpenAIClient
from paper_agents.config import AppConfig, SourceConfig
from paper_agents.models import Paper


class AgentTests(unittest.TestCase):
    def make_config(self) -> AppConfig:
        config = AppConfig()
        config.llm.enabled = False
        config.sources = SourceConfig(
            vla_keywords=["vision-language-action", "manipulation", "diffusion policy"],
            cv_keywords=["segmentation", "object detection", "vision-language"],
        )
        return config

    def test_classifier_finds_vla_robot_paper(self) -> None:
        config = self.make_config()
        paper = Paper(
            paper_id="2501.00001",
            title="Vision-Language-Action Models for Robot Manipulation",
            authors=[],
            abstract="We train a diffusion policy for language-conditioned manipulation.",
            published="",
            updated="",
            categories=["cs.RO", "cs.CV"],
        )
        ClassifierAgent(config).classify(paper)
        self.assertIn("VLA", paper.tags)
        self.assertIn("Robot Learning", paper.tags)
        self.assertGreaterEqual(paper.relevance_score, 4.0)
        self.assertEqual(paper.priority, "must_read")

    def test_classifier_finds_world_model_paper(self) -> None:
        config = self.make_config()
        config.sources.world_model_keywords = ["world model", "latent dynamics", "future prediction"]
        paper = Paper(
            paper_id="2501.00002",
            title="Learning Latent World Models for Future Prediction",
            authors=[],
            abstract="We build a world model with latent dynamics for planning.",
            published="",
            updated="",
            categories=["cs.LG"],
        )
        ClassifierAgent(config).classify(paper)
        self.assertIn("World Model", paper.tags)
        self.assertGreaterEqual(paper.relevance_score, 2.5)

    def test_curator_skips_irrelevant_by_default(self) -> None:
        config = self.make_config()
        relevant = Paper("1", "a", [], "", "", "", [], relevance_score=3, priority="read")
        irrelevant = Paper("2", "b", [], "", "", "", [], relevance_score=0, priority="skip")
        selected = CuratorAgent(config).run([irrelevant, relevant])
        self.assertEqual([paper.paper_id for paper in selected], ["1"])

    def test_notifier_text_contains_summary(self) -> None:
        config = self.make_config()
        paper = Paper(
            paper_id="2501.00001",
            title="A Useful VLA Paper",
            authors=[],
            abstract="",
            published="",
            updated="",
            categories=["cs.CV"],
            abs_url="https://arxiv.org/abs/2501.00001",
            tags=["VLA"],
            relevance_score=4.2,
            summary="本文提出统一策略模型提升机器人操作泛化。",
        )
        text = NotifierAgent(config)._render_text([paper], datetime(2026, 4, 30, tzinfo=timezone.utc), None)
        self.assertIn("论文日报", text)
        self.assertIn("一句话总结：本文提出统一策略模型提升机器人操作泛化。", text)

    def test_fallback_summary_uses_abstract_content(self) -> None:
        config = self.make_config()
        paper = Paper(
            paper_id="2501.00003",
            title="World Model Planning",
            authors=[],
            abstract="We learn a latent dynamics model for robot planning. It improves long-horizon control.",
            published="",
            updated="",
            categories=["cs.RO"],
        )
        SummarizerAgent(config).summarize(paper)
        self.assertIn("latent dynamics model", paper.summary)
        self.assertNotIn("主要贡献见摘要", paper.summary)

    def test_unsupported_deepseek_model_falls_back(self) -> None:
        with patch.dict("os.environ", {"DEEPSEEK_MODEL": "deepseek-v4-flash"}):
            client = OpenAIClient("deepseek-v4-flash", "deepseek")
        self.assertEqual(client.model, "deepseek-chat")

    def test_last_sunday_start_uses_configured_timezone(self) -> None:
        run_date = datetime(2026, 4, 30, 15, 0, tzinfo=timezone.utc)
        start = _last_sunday_start(run_date, "Asia/Shanghai")
        self.assertEqual(start.isoformat(), "2026-04-26T00:00:00+08:00")


if __name__ == "__main__":
    unittest.main()
