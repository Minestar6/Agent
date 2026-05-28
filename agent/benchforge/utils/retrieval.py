"""Wikipedia 检索工具函数。"""

import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from benchforge.schemas import SourceDocument, DocumentStatus


@dataclass
class WikipediaSearchResult:
    """Wikipedia 搜索结果。"""
    title: str
    url: str


def _generate_document_id(url: str) -> str:
    """基于 URL 生成确定性 document_id。

    Args:
        url: 页面 URL

    Returns:
        document_id
    """
    # 使用 URL 的 SHA256 哈希的前 12 个字符
    hash_obj = hashlib.sha256(url.encode('utf-8'))
    return f"doc_{hash_obj.hexdigest()[:12]}"


def search_wikipedia(
    query: str,
    language: str = "en",
    max_pages: int = 5,
) -> list[WikipediaSearchResult]:
    """搜索 Wikipedia 页面。"""
    results = []

    try:
        api_url = f"https://{language}.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": max_pages,
            "format": "json",
        }

        headers = {
            "User-Agent": "BenchForge/0.1.0 (https://github.com/benchforge)"
        }

        response = requests.get(api_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "query" not in data or "search" not in data["query"]:
            return results

        for item in data["query"]["search"]:
            title = item["title"]
            url = f"https://{language}.wikipedia.org/wiki/{title.replace(' ', '_')}"
            results.append(WikipediaSearchResult(title=title, url=url))

    except Exception as e:
        print(f"Wikipedia search failed: {e}")

    return results


def fetch_wikipedia_page(
    result: WikipediaSearchResult,
    run_id: str,
    language: str = "en",
    content_max_length: int = 10000,
) -> SourceDocument:
    """抓取 Wikipedia 页面。

    Args:
        result: 搜索结果
        run_id: 运行 ID
        language: 语言
        content_max_length: 内容最大长度

    Returns:
        源文档
    """
    # 生成确定性 document_id
    document_id = _generate_document_id(result.url)

    headers = {
        "User-Agent": "BenchForge/0.1.0 (https://github.com/benchforge)"
    }

    try:
        response = requests.get(result.url, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # 提取标题
        title = soup.find("h1", {"id": "firstHeading"})
        title_text = title.get_text().strip() if title else result.title

        # 提取摘要（前几段）
        summary_parts = []
        for p in soup.find_all("p", recursive=True):
            text = p.get_text().strip()
            if text and len(text) > 50:
                summary_parts.append(text)
                if len(summary_parts) >= 2:
                    break
        summary = " ".join(summary_parts)

        # 提取内容
        content_div = soup.find("div", {"id": "mw-content-text"})
        content = ""
        if content_div:
            for p in content_div.find_all("p", recursive=True):
                text = p.get_text().strip()
                if text:
                    content += text + "\n"

        # 清理
        content = re.sub(r"\[\d+\]", "", content)
        content = content[:content_max_length]

        return SourceDocument(
            document_id=document_id,
            run_id=run_id,
            topic=result.title,
            language=language,
            title=title_text,
            url=result.url,
            summary=summary,
            content=content,
            status=DocumentStatus.FETCHED,
        )

    except Exception as e:
        return SourceDocument(
            document_id=document_id,
            run_id=run_id,
            topic=result.title,
            language=language,
            title=result.title,
            url=result.url,
            summary="",
            content="",
            metadata={"error": str(e)},
            status=DocumentStatus.FAILED,
        )