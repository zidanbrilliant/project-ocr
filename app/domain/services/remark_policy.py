from app.domain.entities.business_validation_result import BusinessValidationResult


class RemarkPolicy:
    _REMARKS: dict[str, str] = {
        "DOC-R001": "Submitted FILE_PATH is empty.",
        "DOC-R002": "Document is missing from server using submitted FILE_PATH.",
        "DOC-R003": "File corrupt or unreadable.",
        "DOC-R004": "Unsupported document format.",
        "DOC-R005": "File size exceeds maximum limit.",
        "DOC-R006": "Document resolution is below minimum requirement.",
        "DOC-R007": "PDF page count exceeds maximum limit.",
        "INV-R001": "Invoice number not found. Please verify document manually.",
        "INV-R002": "Amount not found. Please verify document manually.",
        "INV-R003": "Billing number not found. Please verify document manually.",
        "INV-R004": "Above Rp. 5.000.000. Missing Stamp Duty.",
        "INV-R005": "Missing company stamp.",
        "INV-R006": "Missing signature.",
        "INV-R007": "Barcode not found or cannot be decoded.",
        "INV-R008": "AI confidence below threshold. Manual verification required.",
        "INV-R009": "Verification passed. Invoice number, amount, signature, company stamp, and required stamp duty are detected.",
        "DN-R001": "Required signature count is not met.",
        "DN-R002": "Required company stamp count is not met.",
        "DN-R003": "Company stamp is detected but color requirement is not met.",
        "DN-R004": "Verification passed. Required signature and company stamp are detected.",
    }

    def generate(self, validation: BusinessValidationResult, doc_error: bool = False) -> str:
        if doc_error:
            return "Document could not be processed, please contact support."
        if validation.passed:
            return "Verification passed."
        if validation.failed_rules:
            return "; ".join(r.message for r in validation.failed_rules[:3])
        return "Verification failed."
