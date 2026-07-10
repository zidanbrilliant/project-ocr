from typing import Final

INV: Final[str] = "INV"
DN: Final[str] = "DN"

ALL_TYPES: Final[frozenset[str]] = frozenset({INV, DN})
INVOICE: Final[str] = "INVOICE"
DELIVERY_NOTE: Final[str] = "DELIVERY_NOTE"

DOC_TYPE_MAP: Final[dict[str, str]] = {
    INV: INVOICE,
    DN: DELIVERY_NOTE,
}
