from dataclasses import dataclass


@dataclass(frozen=True)
class BoundingBox:
    x1: float
    y1: float
    x2: float
    y2: float

    def to_list(self) -> list[float]:
        return [self.x1, self.y1, self.x2, self.y2]

    @classmethod
    def from_list(cls, coords: list[float]) -> "BoundingBox":
        if len(coords) != 4:
            raise ValueError(f"BoundingBox requires 4 coords, got {len(coords)}")
        return cls(x1=coords[0], y1=coords[1], x2=coords[2], y2=coords[3])

    def area(self) -> float:
        return (self.x2 - self.x1) * (self.y2 - self.y1)
