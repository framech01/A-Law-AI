"""
독소조항 정규식 선필터

명확한 독소조항/안전조항은 LLM 호출 없이 즉시 판정합니다.
- 위험 패턴에 매칭 → 위험 점수와 근거 법령을 즉시 반환
- 안전 패턴에 매칭 → 위험 없음으로 즉시 처리
- 둘 다 아니면 None → LLM + RAG 심층 분석 대상
"""
import re
from dataclasses import dataclass

from app.rag.domain import Domain

S = r"\s*"  # 조사/띄어쓰기 변형 허용


@dataclass(frozen=True)
class RiskPattern:
    category: str
    score: int
    patterns: tuple[re.Pattern, ...]
    reason: str
    recommendation: str
    reference_residential: str
    reference_commercial: str


@dataclass
class PrefilterResult:
    category: str
    risk_score: int
    risk_level: str
    reason: str
    legal_reference: str
    recommendation: str


def _c(*patterns: str) -> tuple[re.Pattern, ...]:
    return tuple(re.compile(p) for p in patterns)


RISK_PATTERNS: tuple[RiskPattern, ...] = (
    RiskPattern(
        category="보증금 반환 거부/지연",
        score=90,
        patterns=_c(
            rf"보증금.{{0,30}}(반환하지{S}(않|아니)|반환{S}(을|은)?{S}(거부|유보|지연|보류))",
            rf"(새로운|신규|다음|후속){S}임차인.{{0,25}}(구해|구한|들어|입주|계약).{{0,20}}(후|뒤|때|경우)(에|에만)?.{{0,10}}(보증금)?.{{0,10}}반환",
            rf"보증금.{{0,20}}반환{S}(기한|시기|일자)(은|을|는)?{S}(정하지|명시하지|두지){S}(않|아니)",
        ),
        reason="임대차 종료 시 보증금 반환을 거부·지연하거나 새 임차인 입주를 조건으로 거는 조항은 임차인에게 일방적으로 불리하며 효력이 부정될 수 있습니다.",
        recommendation="'임대차 종료와 동시에(명도와 동시이행으로) 보증금 전액을 반환한다'로 수정하세요.",
        reference_residential="주택임대차보호법 제3조의2, 주택임대차보호법 제10조",
        reference_commercial="상가건물 임대차보호법 제5조, 상가건물 임대차보호법 제15조",
    ),
    RiskPattern(
        category="계약갱신요구권 포기 강요",
        score=88,
        patterns=_c(
            rf"(계약{S})?갱신{S}(요구|청구)(권)?.{{0,15}}(포기|행사하지{S}(않|아니)|행사할{S}수{S}없|(요구|청구)할{S}수{S}없)",
            rf"(갱신|연장)(을|를)?{S}(요구|청구)하지{S}(않|아니)(기로|한다|함)",
        ),
        reason="임차인의 계약갱신요구권을 미리 포기하게 하는 약정은 강행규정에 반해 임차인에게 불리하므로 무효입니다.",
        recommendation="갱신요구권 포기 문구를 삭제하세요. 법정 거절 사유가 없으면 임차인은 1회 갱신을 요구할 수 있습니다.",
        reference_residential="주택임대차보호법 제6조의3, 주택임대차보호법 제10조",
        reference_commercial="상가건물 임대차보호법 제10조, 상가건물 임대차보호법 제15조",
    ),
    RiskPattern(
        category="보증금 전액 몰수",
        score=87,
        patterns=_c(
            rf"보증금.{{0,20}}(전액|전부|모두).{{0,15}}(몰수|몰취|귀속|반환하지{S}(않|아니)|돌려(주지|받지))",
            r"(몰수|몰취)(한다|하기로|됨|된다|할\s*수)",
        ),
        reason="위약 시 보증금 전액을 몰수하는 조항은 부당하게 과다한 손해배상 예정으로 감액되거나 무효가 될 수 있습니다.",
        recommendation="위약금은 통상 계약금 수준으로 정하고, 보증금 몰수 문구는 삭제하세요.",
        reference_residential="민법 제398조, 약관의 규제에 관한 법률 제8조",
        reference_commercial="민법 제398조, 약관의 규제에 관한 법률 제8조",
    ),
    RiskPattern(
        category="임대인 일방 해지/즉시 퇴거",
        score=85,
        patterns=_c(
            rf"임대인.{{0,20}}(언제든지|언제라도|임의로|일방적으로|필요\s*시|필요한\s*경우).{{0,25}}(해지|해제|퇴거|명도|퇴실|나가|비워)",
            rf"즉시{S}(퇴거|명도|퇴실|방을{S}비워|집을{S}비워)",
        ),
        reason="법정 사유 없이 임대인이 언제든 계약을 해지하거나 즉시 퇴거를 요구할 수 있게 하는 조항은 임차인의 존속기간 보장을 침해합니다.",
        recommendation="해지 사유를 법정 사유(차임 2기 연체 등)로 한정하고, 일방 해지·즉시 퇴거 문구는 삭제하세요.",
        reference_residential="주택임대차보호법 제4조, 주택임대차보호법 제10조",
        reference_commercial="상가건물 임대차보호법 제9조, 상가건물 임대차보호법 제15조",
    ),
    RiskPattern(
        category="우선변제권/임차권등기 포기",
        score=85,
        patterns=_c(
            rf"(우선{S}변제권|임차권{S}등기|임차권등기명령|전입{S}신고|확정{S}일자|대항력).{{0,20}}(포기|하지{S}(않|아니|못)|할{S}수{S}없|금지|신청하지|받지{S}(않|아니|못))",
        ),
        reason="전입신고·확정일자·임차권등기 등 보증금 보호 수단을 금지하거나 포기하게 하는 조항은 임차인 보호 규정에 반해 무효이며 보증금 회수 위험을 크게 높입니다.",
        recommendation="해당 문구를 삭제하고, 잔금 지급 당일 전입신고와 확정일자를 반드시 받으세요.",
        reference_residential="주택임대차보호법 제3조, 주택임대차보호법 제3조의2, 주택임대차보호법 제3조의3, 주택임대차보호법 제10조",
        reference_commercial="상가건물 임대차보호법 제3조, 상가건물 임대차보호법 제5조, 상가건물 임대차보호법 제6조, 상가건물 임대차보호법 제15조",
    ),
    RiskPattern(
        category="차임 증액 상한 초과",
        score=80,
        patterns=_c(
            r"(차임|월세|임대료|보증금).{0,25}(매년|매\s*년|1년마다|갱신\s*시).{0,15}([6-9]|[1-9]\d)\s*(%|퍼센트|프로).{0,10}(인상|증액|올)",
            r"(차임|월세|임대료|보증금).{0,15}([6-9]|[1-9]\d)\s*(%|퍼센트|프로).{0,10}(인상|증액)",
        ),
        reason="약정한 차임·보증금 증액 청구는 5%(1/20)를 초과할 수 없으며, 초과 부분은 효력이 없습니다.",
        recommendation="증액률을 연 5% 이내로 수정하세요.",
        reference_residential="주택임대차보호법 제7조, 주택임대차보호법 시행령 제8조",
        reference_commercial="상가건물 임대차보호법 제11조, 상가건물 임대차보호법 시행령 제4조",
    ),
    RiskPattern(
        category="임차인 권리 포기/이의 금지",
        score=75,
        patterns=_c(
            rf"임차인.{{0,20}}(일체의?|모든).{{0,10}}(권리|청구).{{0,10}}포기",
            rf"(이의|민원|소송)(를|을|도|는)?.{{0,6}}(제기할|제기하지|할){S}수{S}없",
            rf"이의(를)?{S}제기하지{S}(않|아니)(기로|한다)",
        ),
        reason="법이 보장하는 임차인의 권리를 일괄 포기하게 하거나 이의 제기를 막는 조항은 임차인에게 불리한 약정으로 효력이 없습니다.",
        recommendation="권리 포기·이의 금지 문구를 삭제하세요.",
        reference_residential="주택임대차보호법 제10조",
        reference_commercial="상가건물 임대차보호법 제15조",
    ),
    RiskPattern(
        category="수선비 전액 임차인 부담",
        score=62,
        patterns=_c(
            rf"(모든|일체의?|전부의?|전체|일체)\s*(수선|수리|보수|하자).{{0,25}}임차인.{{0,10}}(부담|책임|처리)",
            rf"임차인.{{0,10}}(모든|일체의?|전부의?)\s*(수선|수리|보수|하자).{{0,15}}(부담|책임|처리)",
            rf"(보일러|배관|누수|지붕|외벽|구조).{{0,20}}(수리|수선|교체).{{0,15}}임차인.{{0,10}}(부담|책임)",
        ),
        reason="주요 설비·구조부 수선은 원칙적으로 임대인의 의무입니다. 소규모 소모품 외 모든 수선비를 임차인에게 전가하는 조항은 불리합니다.",
        recommendation="'임차인은 전구·소모품 등 소규모 수선만 부담하고, 주요 설비 및 구조부 수선은 임대인이 부담한다'로 범위를 한정하세요.",
        reference_residential="민법 제623조",
        reference_commercial="민법 제623조",
    ),
    RiskPattern(
        category="통상 마모까지 원상복구 의무",
        score=58,
        patterns=_c(
            rf"(자연{S}(마모|노후|손모|훼손)|통상{S}(마모|손모|사용)|경년{S}변화|노후).{{0,30}}(원상{S}복구|원상{S}회복|배상|부담|변상)",
            rf"(도배|장판|벽지).{{0,20}}(새\s*것|신품|전면|전체).{{0,15}}(교체|원상\s*복구).{{0,15}}임차인",
        ),
        reason="통상적인 사용으로 생긴 자연 마모까지 임차인이 원상복구하도록 하는 조항은 원상회복 의무의 범위를 넘어섭니다.",
        recommendation="'통상의 사용에 따른 마모·노후는 원상복구 대상에서 제외한다'를 명시하세요.",
        reference_residential="민법 제615조, 민법 제654조",
        reference_commercial="민법 제615조, 민법 제654조",
    ),
)

SAFE_PATTERNS: tuple[tuple[str, re.Pattern, str], ...] = (
    (
        "보증금 반환 시기 명시",
        re.compile(rf"보증금.{{0,30}}(계약{S}(종료|만료)|명도|퇴거).{{0,20}}(동시에|즉시|당일|이내).{{0,15}}반환(한다|하여야|해야|하기로)"),
        "보증금 반환 시기가 임대차 종료와 동시로 명시되어 있어 임차인 보호에 유리합니다.",
    ),
    (
        "전입신고·확정일자 협조",
        re.compile(rf"(전입{S}신고|확정{S}일자|임차권{S}등기).{{0,20}}(협조|할\s*수\s*있|받을\s*수\s*있|하기로\s*한다|보장)"),
        "임차인의 대항력·우선변제권 확보에 협조하는 조항입니다.",
    ),
    (
        "법령·관례 준용",
        re.compile(rf"(본|이){S}계약(서)?에{S}(정하지|명시되지|규정되지){S}(않은|아니한).{{0,30}}(민법|주택임대차보호법|상가건물\s*임대차보호법|관례|관련{S}법령)"),
        "계약서에 없는 사항은 관련 법령과 관례에 따르는 일반 조항입니다.",
    ),
)


def _normalize(text: str) -> str:
    return re.sub(r"[ \t\r\n]+", " ", text or "").strip()


def classify_contract_domain(text: str) -> Domain:
    if re.search(r"상가|점포|권리금|영업|사업자", text or ""):
        return Domain.COMMERCIAL
    return Domain.RESIDENTIAL


def prefilter_clause(clause_text: str, domain: Domain = Domain.RESIDENTIAL) -> PrefilterResult | None:
    text = _normalize(clause_text)
    if not text:
        return None

    hits = [rp for rp in RISK_PATTERNS if any(p.search(text) for p in rp.patterns)]
    if hits:
        worst = max(hits, key=lambda rp: rp.score)
        others = [rp.category for rp in hits if rp is not worst]
        reason = worst.reason + (f" (함께 탐지: {', '.join(others)})" if others else "")
        reference = worst.reference_commercial if domain == Domain.COMMERCIAL else worst.reference_residential
        return PrefilterResult(
            category=worst.category,
            risk_score=worst.score,
            risk_level=level_from_score(worst.score),
            reason=reason,
            legal_reference=reference,
            recommendation=worst.recommendation,
        )

    for category, pattern, reason in SAFE_PATTERNS:
        if pattern.search(text):
            return PrefilterResult(
                category=category,
                risk_score=5,
                risk_level="Safety",
                reason=reason,
                legal_reference="",
                recommendation="",
            )
    return None


def level_from_score(score: float) -> str:
    if score >= 70:
        return "Risk"
    if score >= 40:
        return "Caution"
    return "Safety"
