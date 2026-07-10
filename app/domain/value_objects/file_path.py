from dataclasses import dataclass


@dataclass(frozen=True)
class FilePath:
    value: str

    def is_http(self) -> bool:
        return self.value.startswith(("http://", "https://"))

    def is_empty(self) -> bool:
        return not self.value.strip()

    def __str__(self) -> str:
        return self.value
