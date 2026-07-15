from app.domain.entities.business_validation_result import BusinessValidationResult


class RemarkPolicy:
    def generate(self, validation: BusinessValidationResult, doc_error: bool = False) -> str:
        if doc_error:
            return "Document cannot be processed. Please contact support."
        if validation.passed:
            return "Verification passed."
        if validation.failed_rules:
            return "; ".join(r.message for r in validation.failed_rules[:3])
        return "Verification failed."
