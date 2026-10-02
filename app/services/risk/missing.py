"""
필수 조항 누락 점검 (규칙 기반)
"""
import re
from dataclasses import dataclass

from app.rag.domain import Domain
from app.schemas.contract import MissingClause


@dataclass(frozen=True)
class RequiredClause:
    name: str
    importance: str
    pattern: re.Pattern
    description: str
    basis_residential: str | None
    basis_commercial: str | None
    domains: tuple[Domain, ...] = (Domain.RESIDENTIAL, Domain.COMMERCIAL)


REQUIRED_CLAUSES: tuple[RequiredClause, ...] = (
    RequiredClause(
        "보증금 및 차임", "critical", re.compile(r"보증금|차\s*임|월\s*세|임대료"),
        "보증금·차임(월세) 금액과 지급 방법이 명시되어 있지 않습니다.", None, None,
    ),
    RequiredClause(
        "임대차 기간", "critical", re.compile(r"(존속|임대차|계약)\s*기간|부터.{0,30}까지"),
        "임대차 기간(시작일·종료일)이 명시되어 있지 않습니다.",
        "주택임대차보호법 제4조", "상가건물 임대차보호법 제9조",
    ),
    RequiredClause(
        "보증금 반환", "critical", re.compile(r"보증금.{0,40}반환|반환.{0,20}보증금"),
        "계약 종료 시 보증금 반환 시기·방법이 명시되어 있지 않습니다.",
        "주택임대차보호법 제3조의2", "상가건물 임대차보호법 제5조",
    ),
    RequiredClause(
        "확정일자·전입신고 안내", "important", re.compile(r"확정\s*일자|전입\s*신고|임차권\s*등기"),
        "확정일자·전입신고(대항력·우선변제권 확보) 관련 내용이 없습니다. 잔금일에 반드시 전입신고와 확정일자를 받으세요.",
        "주택임대차보호법 제3조, 주택임대차보호법 제3조의2", None, (Domain.RESIDENTIAL,),
    ),
    RequiredClause(
        "사업자등록·확정일자 안내", "important", re.compile(r"사업자\s*등록|확정\s*일자"),
        "사업자등록·확정일자(대항력·우선변제권 확보) 관련 내용이 없습니다.",
        None, "상가건물 임대차보호법 제3조, 상가건물 임대차보호법 제5조", (Domain.COMMERCIAL,),
    ),
    RequiredClause(
        "수선 의무", "important", re.compile(r"수\s*선|수\s*리|보\s*수|하\s*자"),
        "목적물 수선(수리) 책임 범위에 관한 조항이 없습니다.", "민법 제623조", "민법 제623조",
    ),
    RequiredClause(
        "계약 해지 조건", "important", re.compile(r"해\s*지|해\s*제"),
        "계약 해지(해제) 사유와 절차가 명시되어 있지 않습니다.", "민법 제640조", "민법 제640조",
    ),
    RequiredClause(
        "원상회복", "recommended", re.compile(r"원상\s*(복구|회복)"),
        "계약 종료 시 원상회복 범위가 명시되어 있지 않습니다.", "민법 제615조, 민법 제654조", "민법 제615조, 민법 제654조",
    ),
    RequiredClause(
        "계약 갱신", "recommended", re.compile(r"갱\s*신|연\s*장"),
        "계약 갱신에 관한 조항이 없습니다. 법정 갱신요구권은 계약서에 없어도 인정됩니다.",
        "주택임대차보호법 제6조, 주택임대차보호법 제6조의3", "상가건물 임대차보호법 제10조",
    ),
)


def find_missing_clauses(text: str, domain: Domain = Domain.RESIDENTIAL) -> list[MissingClause]:
    missing = []
    for rc in REQUIRED_CLAUSES:
        if domain not in rc.domains:
            continue
        if rc.pattern.search(text or ""):
            continue
        basis = rc.basis_commercial if domain == Domain.COMMERCIAL else rc.basis_residential
        missing.append(MissingClause(clause_name=rc.name, importance=rc.importance,
                                     description=rc.description, legal_basis=basis))
    return missing
