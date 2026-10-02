"""
법령 조문 인용 추출 및 검증

LLM이 존재하지 않는 조문(예: '주택임대차보호법 제6조의4')을 인용하는 환각을 막기 위해
응답 속 '법령명 제X조(의Y)' 인용이 실제 검색 근거 문서에 등장하는지 확인하고,
근거에 없는 인용에는 '(미검증)' 표시를 붙입니다.
"""
import re
from dataclasses import dataclass
from typing import Iterable

from app.rag.models import RankedDocument

UNVERIFIED_MARK = "(미검증)"

CITATION_PATTERN = re.compile(
    r"(?P<law>[가-힣]{1,30}(?:법률|시행령|시행규칙|법))\s*제\s*(?P<article>\d+)\s*조(?:\s*의\s*(?P<sub>\d+))?"
)
ARTICLE_PATTERN = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")

# '같은 법', '동법' 처럼 법령명이 아닌 지시어는 검증 대상에서 제외
_SKIP_LAW_NAMES = {"같은법", "동법", "이법", "본법", "해당법", "관련법", "법"}


@dataclass
class Citation:
    law: str
    article: str  # 정규화된 조문 키 (예: 제6조의3)
    start: int
    end: int
    verified: bool = False

    @property
    def label(self) -> str:
        return f"{self.law} {self.article}"


def article_key(article: str, sub: str | None = None) -> str:
    return f"제{int(article)}조" + (f"의{int(sub)}" if sub else "")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _source_articles(text: str) -> set[str]:
    return {article_key(a, s or None) for a, s in ARTICLE_PATTERN.findall(text or "")}


def extract_citations(text: str) -> list[Citation]:
    citations = []
    for m in CITATION_PATTERN.finditer(text or ""):
        law = m.group("law")
        if law in _SKIP_LAW_NAMES:
            continue
        citations.append(Citation(law=law, article=article_key(m.group("article"), m.group("sub")),
                                  start=m.start(), end=m.end()))
    return citations


def verify_citations(answer: str, sources: Iterable[RankedDocument]) -> list[Citation]:
    """
    인용이 근거 문서에 존재하면 verified=True.
    - 같은 문서 안에 법령명과 조문 번호가 모두 있거나
    - 문서 메타데이터(law_name)가 법령명과 일치하고 본문/메타데이터에 조문 번호가 있는 경우
    """
    source_index: list[tuple[str, set[str]]] = []
    for doc in sources:
        meta = doc.metadata or {}
        meta_text = " ".join(str(meta.get(k, "")) for k in ("law_name", "title", "article", "source"))
        combined = f"{meta_text} {doc.content}"
        source_index.append((_normalize(combined), _source_articles(combined)))

    citations = extract_citations(answer)
    for citation in citations:
        law = _normalize(citation.law)
        citation.verified = any(law in text and citation.article in articles for text, articles in source_index)
    return citations


def annotate_unverified_citations(answer: str, sources: Iterable[RankedDocument]) -> tuple[str, list[Citation]]:
    """근거에 없는 인용 뒤에 '(미검증)'을 덧붙인 응답과 인용 목록을 반환"""
    citations = verify_citations(answer, list(sources))
    if not citations:
        return answer, citations

    parts: list[str] = []
    cursor = 0
    for c in citations:
        parts.append(answer[cursor:c.end])
        cursor = c.end
        if not c.verified and not answer[c.end:c.end + len(UNVERIFIED_MARK) + 1].strip().startswith(UNVERIFIED_MARK):
            parts.append(f" {UNVERIFIED_MARK}")
    parts.append(answer[cursor:])
    return "".join(parts), citations
