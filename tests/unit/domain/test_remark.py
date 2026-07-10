import pytest

from app.domain.entities.business_validation_result import BusinessValidationResult, FailedRule
from app.domain.services.remark_policy import RemarkPolicy


@pytest.fixture
def policy() -> RemarkPolicy:
    return RemarkPolicy()


def test_passed_remark(policy: RemarkPolicy) -> None:
    v = BusinessValidationResult(passed=True, return_status="OK", return_code="SUCCESS")
    remark = policy.generate(v)
    assert "passed" in remark.lower()


def test_failed_remark(policy: RemarkPolicy) -> None:
    v = BusinessValidationResult(
        passed=False,
        return_status="NG",
        failed_rules=[FailedRule("INV-R004", "Materai required", "Missing Stamp Duty.")],
    )
    remark = policy.generate(v)
    assert "Stamp Duty" in remark


def test_doc_error_remark(policy: RemarkPolicy) -> None:
    v = BusinessValidationResult(passed=False)
    remark = policy.generate(v, doc_error=True)
    assert "contact support" in remark.lower()
