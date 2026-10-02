from dataclasses import dataclass, field
from typing import Any


@dataclass
class RankedDocument:
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    id: str | None = None

    @property
    def namespace(self) -> str:
        return str(self.metadata.get("namespace", ""))

    @property
    def title(self) -> str:
        meta = self.metadata
        law = meta.get("law_name") or meta.get("title") or meta.get("source") or ""
        article = meta.get("article") or ""
        return f"{law} {article}".strip()
