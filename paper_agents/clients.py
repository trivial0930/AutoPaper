from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from .models import Paper


USER_AGENT = "vla-cv-paper-agents/0.1 (mailto:your-email@example.com)"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
ARXIV_RETRY_DELAYS = [10, 30]


def _request_json(url: str, headers: dict[str, str] | None = None, data: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None
    request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=body, headers=request_headers)
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def _text(element: ET.Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return " ".join(element.text.split())


class ArxivClient:
    base_url = "https://export.arxiv.org/api/query"

    def search_recent(
        self,
        *,
        start: datetime,
        end: datetime,
        categories: list[str],
        max_results_per_category: int,
    ) -> list[Paper]:
        papers: dict[str, Paper] = {}
        for index, category in enumerate(categories):
            if index > 0:
                time.sleep(3.1)
            try:
                category_papers = self._search_category(category, start, end, max_results_per_category)
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ET.ParseError) as error:
                print(f"Warning: arXiv category {category} failed: {error}", file=sys.stderr)
                category_papers = []
            print(f"Collected {len(category_papers)} arXiv papers from {category}", file=sys.stderr)
            for paper in category_papers:
                papers[paper.paper_id] = paper
        return list(papers.values())

    def _search_category(
        self,
        category: str,
        start: datetime,
        end: datetime,
        max_results: int,
    ) -> list[Paper]:
        submitted_range = f"[{_arxiv_date(start)} TO {_arxiv_date(end)}]"
        query = f"cat:{category} AND submittedDate:{submitted_range}"
        params = {
            "search_query": query,
            "start": "0",
            "max_results": str(max_results),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
        root = self._fetch_atom(url)
        return [_entry_to_paper(entry) for entry in root.findall("atom:entry", ATOM_NS)]

    def _fetch_atom(self, url: str) -> ET.Element:
        last_error: Exception | None = None
        delays = [0, *ARXIV_RETRY_DELAYS]
        for attempt, delay in enumerate(delays, start=1):
            if delay:
                time.sleep(delay)
            try:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = response.read()
                if payload.strip().lower().startswith(b"rate exceeded"):
                    raise RuntimeError("arXiv rate limit exceeded")
                return ET.fromstring(payload)
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ET.ParseError, RuntimeError) as error:
                last_error = error
                if attempt < len(delays):
                    print(f"Warning: arXiv request failed on attempt {attempt}: {error}; retrying...", file=sys.stderr)
        if last_error:
            raise last_error
        raise RuntimeError("arXiv request failed")


def _arxiv_date(value: datetime) -> str:
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y%m%d%H%M")


def _entry_to_paper(entry: ET.Element) -> Paper:
    raw_id = _text(entry.find("atom:id", ATOM_NS))
    arxiv_id = raw_id.rstrip("/").split("/")[-1]
    versionless_id = arxiv_id.split("v")[0]
    links = entry.findall("atom:link", ATOM_NS)
    pdf_url = ""
    for link in links:
        if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
            pdf_url = link.attrib.get("href", "")
            break
    categories = [node.attrib.get("term", "") for node in entry.findall("atom:category", ATOM_NS)]
    primary = entry.find("arxiv:primary_category", ATOM_NS)
    authors = [_text(author.find("atom:name", ATOM_NS)) for author in entry.findall("atom:author", ATOM_NS)]
    return Paper(
        paper_id=versionless_id,
        title=_text(entry.find("atom:title", ATOM_NS)),
        authors=[author for author in authors if author],
        abstract=_text(entry.find("atom:summary", ATOM_NS)),
        published=_text(entry.find("atom:published", ATOM_NS)),
        updated=_text(entry.find("atom:updated", ATOM_NS)),
        categories=[category for category in categories if category],
        abs_url=f"https://arxiv.org/abs/{versionless_id}",
        pdf_url=pdf_url or f"https://arxiv.org/pdf/{versionless_id}",
        primary_category=primary.attrib.get("term", "") if primary is not None else "",
    )


class SemanticScholarClient:
    base_url = "https://api.semanticscholar.org/graph/v1/paper"

    def __init__(self, sleep_seconds: float = 1.0):
        self.sleep_seconds = sleep_seconds
        self.api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")

    def enrich(self, paper: Paper) -> Paper:
        fields = ",".join(
            [
                "title",
                "abstract",
                "url",
                "tldr",
                "citationCount",
                "venue",
                "externalIds",
                "openAccessPdf",
                "fieldsOfStudy",
                "publicationDate",
            ]
        )
        url = f"{self.base_url}/arXiv:{urllib.parse.quote(paper.paper_id)}?fields={fields}"
        headers = {"User-Agent": USER_AGENT}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        try:
            data = _request_json(url, headers=headers)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            return paper
        finally:
            time.sleep(self.sleep_seconds)

        tldr = data.get("tldr") or {}
        if isinstance(tldr, dict):
            paper.semantic_tldr = tldr.get("text", "") or paper.semantic_tldr
        paper.citation_count = data.get("citationCount", paper.citation_count)
        paper.venue = data.get("venue") or paper.venue
        open_pdf = data.get("openAccessPdf") or {}
        if isinstance(open_pdf, dict) and open_pdf.get("url"):
            paper.pdf_url = open_pdf["url"]
        return paper


class OpenAIClient:
    base_url = "https://api.openai.com/v1/responses"

    def __init__(self, model: str, provider: str = "openai"):
        self.provider = os.environ.get("LLM_PROVIDER", provider).lower()
        self.model = self._model_from_env(model)
        self.api_key = self._api_key_from_env()

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, system: str, user: str) -> str:
        if not self.api_key:
            raise RuntimeError(f"{self.provider} API key is not set")
        if self.provider == "deepseek":
            return self._deepseek_complete(system, user)
        return self._openai_complete(system, user)

    def _model_from_env(self, default: str) -> str:
        if self.provider == "deepseek":
            return os.environ.get("DEEPSEEK_MODEL", default)
        return os.environ.get("OPENAI_MODEL", default)

    def _api_key_from_env(self) -> str:
        if self.provider == "deepseek":
            return os.environ.get("DEEPSEEK_API_KEY", "")
        return os.environ.get("OPENAI_API_KEY", "")

    def _openai_complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        data = _request_json(
            self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}", "User-Agent": USER_AGENT},
            data=payload,
        )
        if data.get("output_text"):
            return str(data["output_text"]).strip()
        return _extract_response_text(data).strip()

    def _deepseek_complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }
        data = _request_json(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "User-Agent": USER_AGENT},
            data=payload,
        )
        choices = data.get("choices", [])
        if not choices:
            return ""
        message = choices[0].get("message", {})
        return str(message.get("content", "")).strip()


class FeishuClient:
    def __init__(self, webhook_url: str, secret: str = ""):
        self.webhook_url = webhook_url
        self.secret = secret

    def send_text(self, text: str) -> bool:
        if not self.webhook_url:
            return False
        payload: dict[str, Any] = {
            "msg_type": "text",
            "content": {"text": text},
        }
        if self.secret:
            timestamp = str(int(time.time()))
            payload["timestamp"] = timestamp
            payload["sign"] = _feishu_sign(timestamp, self.secret)
        data = _request_json(self.webhook_url, data=payload)
        code = data.get("code", data.get("StatusCode", 0))
        if code not in (0, "0", None):
            message = data.get("msg") or data.get("StatusMessage") or data
            raise RuntimeError(f"Feishu notification failed: {message}")
        return True


def _feishu_sign(timestamp: str, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), b"", digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _extract_response_text(data: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(content["text"])
    return "\n".join(chunks)
