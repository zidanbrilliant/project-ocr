# Final Review Fix Report

## Outcome

Resolved all four whole-branch review findings without changing datasets,
models, dependencies, or external integrations:

- Failed benchmark rows now force every labeled field check to `False`.
  Nullable labels match only an explicit field result with
  `status: NOT_FOUND`; an absent field or a null value without that status is
  a mismatch.
- Color evidence remains present in raw and canonical output with
  `evaluation_status: not_evaluated`. The shared production default and
  example configuration still require color; only `DirectProcessor` injects
  a local rule configuration that disables color validation.
- Page `ai_note` text reports `barcode decoded`, `barcode found`, or
  `barcode not found` exclusively from barcode item flags.
- The in-memory local runtime reports `FAILED` when every document failed and
  reserves `PARTIAL_SUCCESS` for mixed outcomes.

## TDD Evidence

The focused regression command was run before production changes:

```text
pytest -q \
  tests/unit/application/test_model_evaluation_service.py::test_evaluate_fields_does_not_match_an_absent_nullable_field \
  tests/unit/test_benchmark_pipeline.py::test_benchmark_marks_every_labeled_field_mismatched_on_processing_error \
  tests/unit/domain/test_business_rules.py::test_local_default_policy_keeps_color_output_only \
  tests/unit/application/test_result_builder.py::test_result_envelope_includes_local_identifiers_and_deterministic_page_note \
  tests/unit/application/test_result_builder.py::test_result_envelope_page_note_does_not_claim_an_undetected_barcode \
  tests/unit/application/test_local_runtime.py::test_store_marks_job_failed_when_every_document_failed
```

RED result:

```text
6 failed
```

An additional nullable-field status regression was then run RED:

```text
pytest -q tests/unit/application/test_model_evaluation_service.py::test_evaluate_fields_requires_not_found_status_for_nullable_field
1 failed
```

After the minimal fixes, the expanded focused command passed:

```text
8 passed, 1 warning
```

The warning is the existing unrecognized `asyncio_mode` pytest configuration
when the optional plugin is unavailable.

## Verification

```text
pytest -q tests/unit/application/test_model_evaluation_service.py \
  tests/unit/test_benchmark_pipeline.py \
  tests/unit/domain/test_business_rules.py \
  tests/unit/application/test_result_builder.py \
  tests/unit/application/test_local_runtime.py \
  tests/unit/test_direct_processor.py \
  tests/integration/test_local_e2e.py
47 passed, 1 warning

pytest -q
158 passed, 2 warnings

python -m compileall -q app scripts tests
exit 0

python -m ruff check \
  app/application/services/model_evaluation_service.py \
  scripts/benchmark_pipeline.py \
  app/shared/config/settings.py \
  app/application/services/result_builder.py \
  app/application/services/local_runtime.py \
  tests/unit/application/test_model_evaluation_service.py \
  tests/unit/test_benchmark_pipeline.py \
  tests/unit/domain/test_business_rules.py \
  tests/unit/application/test_result_builder.py \
  tests/unit/application/test_local_runtime.py \
  tests/integration/test_local_e2e.py \
  --ignore E501
All checks passed!

git diff --check
no whitespace errors
```

The second full-suite warning is the existing `datetime.utcnow()`
deprecation in `app/shared/utils/id_generator.py`. A full-repository Ruff run
was also executed and exposed the repository's existing broad lint backlog;
the scoped changed-file gate above is clean, with existing long-line findings
ignored consistently with earlier task reports.

## Scope

Changed only local benchmark evaluation, local runtime/configuration,
canonical page-note behavior, their regression tests, and this report. No
dataset, model, dependency manifest, database, broker, or external integration
content was altered.

Planned commit subject:

```text
fix: address final branch review findings
```

## Final Follow-up Review

Two additional review findings were fixed:

- Restored `REQUIRE_COLORED_DOCUMENT=true` in shared settings and
  `.env.example`. `DirectProcessor` now explicitly injects
  `RuleConfig(require_colored_document=False)`, leaving worker/orchestrator
  construction on the configurable production evaluator.
- Local execution now derives a terminal envelope status from document
  outcomes. When all documents fail, the snapshot, header processing status,
  header processing result, and envelope processing status are all `FAILED`.
  Mixed outcomes remain `PARTIAL_SUCCESS`.
- Streamlit now renders a stored failed-job envelope through the normal
  per-document detail/JSON path. The generic failure message is used only when
  a failed job has no stored result, such as a warmup or infrastructure
  failure.

### Follow-up TDD Evidence

The initial focused RED run produced three expected failures:

```text
3 failed, 1 passed
```

The local `DirectProcessor` policy test initially passed only because the
shared setting was still incorrectly false. After restoring the production
default first, it independently went RED:

```text
1 failed, 1 passed
FAILED test_direct_processor_disables_color_rule_only_for_local_flow
```

After local policy injection and failed-result rendering were implemented:

```text
pytest -q \
  tests/unit/domain/test_business_rules.py::test_production_default_policy_still_requires_colored_documents \
  tests/unit/test_direct_processor.py::test_direct_processor_disables_color_rule_only_for_local_flow \
  tests/unit/application/test_local_execution_service.py::test_run_inline_marks_all_failed_result_envelope_failed \
  tests/unit/test_upload_app.py
5 passed, 1 warning
```

### Follow-up Verification

```text
pytest -q tests/unit/domain/test_business_rules.py \
  tests/unit/test_direct_processor.py \
  tests/unit/application/test_local_execution_service.py \
  tests/unit/application/test_result_builder.py \
  tests/unit/test_upload_app.py \
  tests/integration/test_local_e2e.py
31 passed, 1 warning

pytest -q
162 passed, 2 warnings

python -m compileall -q app scripts tests
exit 0

python -m ruff check \
  app/shared/config/settings.py \
  app/application/services/local_execution_service.py \
  app/application/services/result_builder.py \
  scripts/direct_processor.py \
  scripts/upload_app.py \
  tests/unit/domain/test_business_rules.py \
  tests/unit/test_direct_processor.py \
  tests/unit/application/test_local_execution_service.py \
  tests/unit/test_upload_app.py \
  --ignore E501
All checks passed!

git diff --check
no whitespace errors
```

Follow-up commit subject:

```text
fix: preserve production color policy and failed local results
```

## Settings-Preservation Follow-up

The final review identified that constructing
`RuleConfig(require_colored_document=False)` also replaced settings-derived
local policy values with dataclass defaults. The regression now verifies that
`DirectProcessor` keeps:

- `REQUIRE_INVOICE_NUMBER`
- `CONFIDENCE_THRESHOLD`
- `REQUIRE_STAMP_FOR_INVOICE`
- `REQUIRE_MATERAI_ABOVE_THRESHOLD`
- `AMOUNT_STAMP_DUTY_THRESHOLD`
- `AMOUNT_MATCH_TOLERANCE`

while changing only `require_colored_document` to `False`. Signature, barcode,
delivery-note counts, and every other default-evaluator value come from the
same shared settings-derived `RuleConfig` builder.

### TDD Evidence

The extended local-policy regression failed before implementation:

```text
FAILED test_direct_processor_disables_color_rule_only_for_local_flow
assert True == False
where require_invoice_number=True
and settings.REQUIRE_INVOICE_NUMBER=False
```

The implementation extracts the existing settings mapping into
`default_rule_config()` and uses:

```text
replace(default_rule_config(), require_colored_document=False)
```

Focused GREEN:

```text
pytest -q \
  tests/unit/test_direct_processor.py::test_direct_processor_disables_color_rule_only_for_local_flow \
  tests/unit/domain/test_business_rules.py
11 passed, 1 warning
```

Final verification:

```text
pytest -q
162 passed, 2 warnings

python -m compileall -q app scripts tests
exit 0

python -m ruff check \
  app/domain/services/business_rule_evaluator.py \
  scripts/direct_processor.py \
  tests/unit/test_direct_processor.py \
  --ignore E501,I001,F401,SIM102
All checks passed!

git diff --check
no whitespace errors
```

The ignored Ruff rules are pre-existing findings in the legacy business-rule
module; the changed config-builder and local override lines are clean.

Final follow-up commit subject:

```text
fix: preserve local rule settings when disabling color
```
