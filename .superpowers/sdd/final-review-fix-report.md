# Final Review Fix Report

## Outcome

Resolved all four whole-branch review findings without changing datasets,
models, dependencies, or external integrations:

- Failed benchmark rows now force every labeled field check to `False`.
  Nullable labels match only an explicit field result with
  `status: NOT_FOUND`; an absent field or a null value without that status is
  a mismatch.
- Color evidence remains present in raw and canonical output with
  `evaluation_status: not_evaluated`, while the local default and example
  configuration disable color as a business-validation rule.
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
