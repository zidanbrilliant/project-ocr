import re
from dataclasses import dataclass

_RUPIAH_CLEAN = re.compile(r"[Rp\s\.]")
_COMMA_DECIMAL = re.compile(r",(\d{2})$")


@dataclass(frozen=True)
class MoneyAmount:
    value: float
    currency: str = "IDR"

    @classmethod
    def parse_rupiah(cls, raw: str) -> "MoneyAmount | None":
        cleaned = _RUPIAH_CLEAN.sub("", raw.strip())
        cleaned = _COMMA_DECIMAL.sub(r".\1", cleaned)
        try:
            return cls(value=float(cleaned))
        except (ValueError, TypeError):
            return None

    def __gt__(self, other: float) -> bool:
        return self.value > other

    def __ge__(self, other: float) -> bool:
        return self.value >= other
