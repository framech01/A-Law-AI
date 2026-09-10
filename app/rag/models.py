from dataclasses import dataclass, field
from typing import Any

@dataclass
class RankedDocument:
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    id: str | None = None
