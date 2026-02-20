"""
AI Summarizer Module
Uses Claude (Anthropic) to summarize Naver Cafe posts into structured bullet points.
"""

import logging
from anthropic import Anthropic

from .scraper import CafePost

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
당신은 회의록 및 커뮤니티 게시글 요약 전문가입니다.
주어진 게시글을 분석하여 핵심 정보만을 추출하고, 명확한 구조로 정리합니다.
"""

USER_PROMPT_TEMPLATE = """\
다음 네이버 카페 게시글을 분석하여 핵심 내용을 요약해주세요.

---
제목: {title}
작성자: {author}
작성일: {date}

본문:
{content}
---

아래 형식에 맞춰 요약해주세요. 각 섹션에 해당하는 내용이 없으면 "해당 없음"으로 표시하세요.

**📋 핵심 주제**
- (이 게시글에서 주요하게 다루는 주제나 논의 사항)

**✅ 결정된 사항**
- (논의 결과 확정된 내용, 합의된 사항)

**📌 향후 행동 지침 (Action Items)**
- (앞으로 해야 할 일, 담당자 및 마감일이 있으면 함께 표기)

규칙:
- 불렛 포인트 형식 사용 (하이픈 `-` 사용)
- 인사말, 서론, 결론 등 불필요한 서술 제외
- 핵심 내용만 간결하게 작성
- 한국어로 작성
"""


class AISummarizer:
    """
    Summarizes a CafePost using the Anthropic Claude API.

    Usage:
        summarizer = AISummarizer(api_key="sk-ant-...")
        summary_text = summarizer.summarize(post)
    """

    DEFAULT_MODEL = "claude-sonnet-4-6"
    MAX_CONTENT_CHARS = 8_000  # Truncate very long posts before sending to API

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self.client = Anthropic(api_key=api_key)
        self.model = model

    def summarize(self, post: CafePost) -> str:
        """
        Generate a structured summary for the given post.

        Returns the summary as a plain string (Markdown formatted).
        """
        logger.info("Summarizing post %d: %.60s", post.id, post.title)

        content = post.content
        if len(content) > self.MAX_CONTENT_CHARS:
            logger.debug(
                "Post %d content truncated from %d to %d chars.",
                post.id, len(content), self.MAX_CONTENT_CHARS,
            )
            content = content[: self.MAX_CONTENT_CHARS] + "\n\n[... 내용이 길어 일부 생략됨]"

        prompt = USER_PROMPT_TEMPLATE.format(
            title=post.title or "(제목 없음)",
            author=post.author or "알 수 없음",
            date=post.date or "알 수 없음",
            content=content or "(내용 없음)",
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1_024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        summary = response.content[0].text.strip()
        logger.info("Summary generated for post %d (%d chars).", post.id, len(summary))
        return summary
