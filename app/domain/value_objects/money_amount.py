import re
from dataclasses import dataclass

_NON_NUMERIC = re.compile(r"[^0-9,.-]")


@dataclass(frozen=True)
class MoneyAmount:
    value: float
    currency: str = "IDR"

    @classmethod
    def parse_rupiah(cls, raw: str) -> "MoneyAmount | None":
        cleaned = _NON_NUMERIC.sub("", raw.strip())
        if not cleaned:
            return None
        if "," in cleaned and "." in cleaned:
            decimal = "," if cleaned.rfind(",") > cleaned.rfind(".") else "."
            cleaned = cleaned.replace("." if decimal == "," else ",", "")
            if decimal == ",":
                cleaned = cleaned.replace(",", ".")
        elif cleaned.count(",") > 1:
            parts = cleaned.rsplit(",", 1)
            if len(parts[1]) <= 2:
                cleaned = parts[0].replace(",", "") + "." + parts[1]
            else:
                cleaned = cleaned.replace(",", "")
        elif cleaned.count(".") > 1:
            parts = cleaned.rsplit(".", 1)
            if len(parts[1]) <= 2:
                cleaned = parts[0].replace(".", "") + "." + parts[1]
            else:
                cleaned = cleaned.replace(".", "")
        elif "," in cleaned:
            trailing = cleaned.rsplit(",", 1)[1]
            if len(trailing) <= 2:
                cleaned = cleaned.replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif "." in cleaned:
            trailing = cleaned.rsplit(".", 1)[1]
            if len(trailing) <= 2:
                pass
            else:
                cleaned = cleaned.replace(".", "")
        else:
            cleaned = cleaned.replace(",", ".")
        try:
            return cls(value=float(cleaned))
        except (ValueError, TypeError):
            return None

    def __gt__(self, other: float) -> bool:
        return self.value > other

    def __ge__(self, other: float) -> bool:
        return self.value >= other
