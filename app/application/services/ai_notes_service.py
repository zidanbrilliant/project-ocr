from app.domain.entities.business_validation_result import BusinessValidationResult
from app.domain.services.remark_policy import RemarkPolicy


class AINotesService:
    def __init__(self) -> None:
        self._policy = RemarkPolicy()

    def generate_remark(self, validation: BusinessValidationResult, doc_error: bool = False) -> str:
        return self._policy.generate(validation, doc_error)

    def generate_document_note(self, result: str, failed_rules: list[str] | None = None) -> str:
        if result == "OK":
            return "Document successfully verified."
        if failed_rules:
            top = failed_rules[0]
            return f"Verification failed: {top}."
        return "Document verification failed."

    def generate_job_note(self, total: int, ok_count: int) -> str:
        if total == ok_count:
            return "All mandatory document validations passed successfully."
        return f"{total - ok_count} document(s) failed mandatory validation."
