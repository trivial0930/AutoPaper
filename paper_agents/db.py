from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from .models import Paper


class PaperStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS papers (
                paper_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                updated TEXT,
                priority TEXT,
                relevance_score REAL,
                payload TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def upsert_many(self, papers: list[Paper]) -> None:
        rows = [
            (
                paper.paper_id,
                paper.title,
                paper.updated,
                paper.priority,
                paper.relevance_score,
                json.dumps(asdict(paper), ensure_ascii=False),
            )
            for paper in papers
        ]
        self.connection.executemany(
            """
            INSERT INTO papers (paper_id, title, updated, priority, relevance_score, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(paper_id) DO UPDATE SET
                title = excluded.title,
                updated = excluded.updated,
                priority = excluded.priority,
                relevance_score = excluded.relevance_score,
                payload = excluded.payload
            """,
            rows,
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
