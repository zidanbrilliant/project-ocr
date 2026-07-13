from app.domain.entities.business_validation_result import BusinessValidationResult


class RemarkPolicy:
    def generate(self, validation: BusinessValidationResult) -> str:
        if validation.passed:
            return "Verification passed."
        if validation.failed_rules:
            return "; ".join(r.message for r in validation.failed_rules[:3])
        return "Verification failed."
