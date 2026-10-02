"""
계약서 텍스트 → 조항 단위 분리

지원 형태
- '제1조 (목적물) ...' 형태의 조문
- '특약사항' 섹션 아래 '1.', '1)', '①', '-', '•' 등으로 나열된 특약
- 위 구조가 없으면 빈 줄 기준 문단
"""
import re
from dataclasses import dataclass

ARTICLE_HEAD = re.compile(r"(?m)^[ \t#*>|]*(제\s*\d+\s*조(?:\s*의\s*\d+)?)\s*(?:[(\[【<]\s*([^)\]】>\n]{1,30})\s*[)\]】>])?")
SPECIAL_HEAD = re.compile(r"^[ \t#*>|]*\[?\s*특\s*약\s*(?:사\s*항|조\s*항)?\s*\]?\s*(?:[:：]|$)", re.M)
ITEM_HEAD = re.compile(r"(?m)^[ \t|]*(?:(\d{1,2})\s*[.)]|([①-⑳])|[-•·▪*]\s)\s*")
# 서명/날인/중개사 정보 등 분석 대상이 아닌 꼬리 부분
TAIL_MARKERS = re.compile(r"(?m)^[ \t#*>|]*(본\s*계약을\s*증명하기\s*위하여|임\s*대\s*인\s*[:：]?\s*주\s*소|개업\s*공인\s*중개사)")

MIN_CLAUSE_CHARS = 8


@dataclass
class Clause:
    index: int
    title: str
    content: str
    kind: str = "article"  # article | special | paragraph

    @property
    def text(self) -> str:
        return f"{self.title} {self.content}".strip()


def _clean(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"<[^>]+>", " ", text)  # Upstage markdown/html 잔재
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _split_special(section: str, start_index: int) -> list[Clause]:
    matches = list(ITEM_HEAD.finditer(section))
    clauses: list[Clause] = []
    if not matches:
        body = section.strip()
        if len(body) >= MIN_CLAUSE_CHARS:
            clauses.append(Clause(start_index, "특약사항", body, "special"))
        return clauses
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(section)
        body = section[m.end():end].strip()
        if len(body) < MIN_CLAUSE_CHARS:
            continue
        clauses.append(Clause(start_index + len(clauses), f"특약 {len(clauses) + 1}", body, "special"))
    return clauses


def split_clauses(text: str) -> list[Clause]:
    text = _clean(text)
    if not text:
        return []

    tail = TAIL_MARKERS.search(text)
    special = SPECIAL_HEAD.search(text)
    special_start = special.start() if special else None

    main_end = special_start if special_start is not None else len(text)
    main = text[:main_end]

    clauses: list[Clause] = []
    heads = list(ARTICLE_HEAD.finditer(main))
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(main)
        if tail and tail.start() > m.start():
            end = min(end, tail.start())
        number = re.sub(r"\s+", "", m.group(1))
        name = (m.group(2) or "").strip()
        title = f"{number} ({name})" if name else number
        body = main[m.end():end].strip(" \n:：.")
        if len(body) >= 2:
            clauses.append(Clause(len(clauses), title, body, "article"))

    if special is not None:
        section_end = len(text)
        if tail and tail.start() > special.end():
            section_end = tail.start()
        clauses.extend(_split_special(text[special.end():section_end], len(clauses)))

    if clauses:
        return clauses

    # 구조가 없는 텍스트: 빈 줄 기준 문단
    body_end = tail.start() if tail else len(text)
    for para in re.split(r"\n\s*\n", text[:body_end]):
        para = para.strip()
        if len(para) >= MIN_CLAUSE_CHARS:
            clauses.append(Clause(len(clauses), f"문단 {len(clauses) + 1}", para, "paragraph"))
    return clauses
