from dataclasses import dataclass, field
from typing import Any


@dataclass
class FailedRule:
    rule_id: str
    rule_name: str
    message: str


@dataclass
class BusinessValidationResult:
    passed: bool = False
    return_status: str = "NG"
    return_code: str = "SUCCESS"
    failed_rules: list[FailedRule] = field(default_factory=list)
    remark: str = ""
