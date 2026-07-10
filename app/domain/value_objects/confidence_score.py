from dataclasses import dataclass


@dataclass(frozen=True)
class ConfidenceScore:
    value: float

    def __post_init__(self) -> None:
        if not (0 <= self.value <= 100):
            raise ValueError(f"Confidence must be 0-100, got {self.value}")

    def is_above_threshold(self, threshold: int = 80) -> bool:
        return self.value >= threshold

    def to_int(self) -> int:
        return round(self.value)

    @classmethod
    def level(cls, value: float | None) -> str | None:
        if value is None:
            return None
        if value >= 95:
            return "Very High"
        if value >= 80:
            return "High"
        if value >= 60:
            return "Medium"
        return "Low"
