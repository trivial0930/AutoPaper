from __future__ import annotations

import unittest

from paper_agents.agents import ClassifierAgent, CuratorAgent
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

    def test_curator_skips_irrelevant_by_default(self) -> None:
        config = self.make_config()
        relevant = Paper("1", "a", [], "", "", "", [], relevance_score=3, priority="read")
        irrelevant = Paper("2", "b", [], "", "", "", [], relevance_score=0, priority="skip")
        selected = CuratorAgent(config).run([irrelevant, relevant])
        self.assertEqual([paper.paper_id for paper in selected], ["1"])


if __name__ == "__main__":
    unittest.main()
