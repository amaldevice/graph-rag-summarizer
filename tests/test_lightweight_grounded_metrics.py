from evaluation.evaluator import SummaryEvaluator
from evaluation.quality_checker import QualityChecker


def _source_chunks():
    return [
        {
            "chunk_id": "results-1",
            "text": "NASA reported 42% growth in 2024.",
            "hierarchy": {"section_id": "results"},
        },
        {
            "chunk_id": "discussion-1",
            "text": "ESA confirmed the outcome after review.",
            "hierarchy": {"section_id": "discussion"},
        },
    ]


def test_lightweight_metrics_trace_supported_facts_to_diverse_chunk_ids():
    result = SummaryEvaluator().evaluate_without_reference(
        "NASA reported 42% growth in 2024. ESA confirmed the outcome after review.",
        source_chunks=_source_chunks(),
        query="NASA ESA outcome",
    )

    metrics = result["grounded_metrics"]
    assert set(metrics) == {
        "factcc",
        "summac",
        "geval",
        "qa_coverage",
        "entity_consistency",
        "number_date_consistency",
        "sentence_support",
        "citation_coverage",
        "redundancy",
        "query_relevance",
        "evidence_diversity",
    }
    for name in (
        "entity_consistency",
        "number_date_consistency",
        "sentence_support",
        "citation_coverage",
        "redundancy",
        "query_relevance",
        "evidence_diversity",
    ):
        assert metrics[name]["status"] == "available"
        assert metrics[name]["score"] >= 0.9
    assert metrics["citation_coverage"]["details"]["supporting_chunk_ids"] == [
        "results-1",
        "discussion-1",
    ]
    assert metrics["citation_coverage"]["details"]["sentence_support"] == [
        {
            "sentence_index": 0,
            "sentence": "NASA reported 42% growth in 2024.",
            "chunk_id": "results-1",
            "support_score": 1.0,
        },
        {
            "sentence_index": 1,
            "sentence": "ESA confirmed the outcome after review.",
            "chunk_id": "discussion-1",
            "support_score": 1.0,
        },
    ]
    assert QualityChecker(min_summary_words=1).check(result)["status"] == "PASS"


def test_unsupported_number_or_date_fails_the_grounded_quality_gate():
    result = SummaryEvaluator().evaluate_without_reference(
        "NASA reported 99% growth in 2025.",
        source_chunks=_source_chunks(),
        query="NASA reported",
    )

    quality = QualityChecker(min_summary_words=1).check(result)

    assert result["grounded_metrics"]["number_date_consistency"]["score"] == 0.0
    assert any("number_date_consistency" in issue for issue in quality["issues"])
    assert QualityChecker(min_summary_words=1).suggest_action(quality)["action"] == "retry_prompt"


def test_atomic_dates_and_partial_number_mismatches_fail_the_quality_gate():
    date_result = SummaryEvaluator().evaluate_without_reference(
        "NASA reported results on August 15, 2026.",
        source_chunks=[{
            "chunk_id": "date-1",
            "text": "NASA reported results on July 15, 2026.",
            "hierarchy": {"section_id": "results"},
        }],
        query="NASA results",
    )
    partial_result = SummaryEvaluator().evaluate_without_reference(
        "NASA reported 42% growth in 2025.",
        source_chunks=_source_chunks(),
        query="NASA growth",
    )

    assert date_result["grounded_metrics"]["number_date_consistency"]["score"] == 0.0
    assert partial_result["grounded_metrics"]["number_date_consistency"]["score"] == 0.5
    quality = QualityChecker(min_summary_words=1).check(partial_result)
    assert quality["metric_decisions"]["number_date_consistency"]["decision"] == "fail"
    assert "< 1.0000" in next(issue for issue in quality["issues"] if "number_date_consistency" in issue)


def test_common_date_formats_and_signed_numbers_remain_atomic():
    evaluator = SummaryEvaluator()

    assert evaluator._numbers_and_dates("The event was 15 August 2026.") != evaluator._numbers_and_dates(
        "The event was 15 July 2026."
    )
    assert evaluator._numbers_and_dates("The event was 04/05/2024.") != evaluator._numbers_and_dates(
        "The event was 05/04/2024."
    )
    assert evaluator._numbers_and_dates("The event was Feb. 15, 2026.") != evaluator._numbers_and_dates(
        "The event was Jan. 15, 2026."
    )
    assert evaluator._numbers_and_dates("The event was Jul. 15, 2026.") == evaluator._numbers_and_dates(
        "The event was July 15, 2026."
    )
    assert evaluator._numbers_and_dates("The event was 04/05/2024.") == evaluator._numbers_and_dates(
        "The event was 4/5/2024."
    )
    assert evaluator._numbers_and_dates("The event was 2024-04-05.") == evaluator._numbers_and_dates(
        "The event was 2024/4/5."
    )
    assert evaluator._numbers_and_dates("The temperature was 5 C.") != evaluator._numbers_and_dates(
        "The temperature was -5 C."
    )


def test_unsupported_entities_and_sentences_retry_the_prompt_stage():
    result = SummaryEvaluator().evaluate_without_reference(
        "MARS reported growth novel discovery.",
        source_chunks=_source_chunks(),
        query="MARS reported",
    )

    quality = QualityChecker(min_summary_words=1).check(result)

    assert result["grounded_metrics"]["entity_consistency"]["score"] == 0.0
    assert result["grounded_metrics"]["sentence_support"]["score"] == 0.0
    assert QualityChecker(min_summary_words=1).suggest_action(quality)["action"] == "retry_prompt"


def test_single_token_named_entities_are_checked_against_the_source():
    result = SummaryEvaluator().evaluate_without_reference(
        "Alice led the study.",
        source_chunks=[{
            "chunk_id": "people-1",
            "text": "Bob led the study.",
            "hierarchy": {"section_id": "people"},
        }],
        query="Alice study",
    )

    assert result["grounded_metrics"]["entity_consistency"]["score"] == 0.0


def test_discourse_markers_are_not_treated_as_named_entities():
    result = SummaryEvaluator().evaluate_without_reference(
        "Notably, the findings are consistent. Additionally, the evidence is clear.",
        source_chunks=[{
            "chunk_id": "findings-1",
            "text": "The findings are consistent. The evidence is clear.",
            "hierarchy": {"section_id": "results"},
        }],
        query="findings evidence",
    )

    assert result["grounded_metrics"]["entity_consistency"]["score"] == 1.0


def test_low_query_relevance_retries_retrieval():
    result = SummaryEvaluator().evaluate_without_reference(
        "NASA reported 42% growth in 2024.",
        source_chunks=_source_chunks(),
        query="ocean biology",
    )

    quality = QualityChecker(min_summary_words=1).check(result)

    assert result["grounded_metrics"]["query_relevance"]["score"] == 0.0
    assert QualityChecker(min_summary_words=1).suggest_action(quality)["action"] == "retry_retrieval"


def test_missing_chunk_identity_keeps_traceability_metrics_unavailable():
    result = SummaryEvaluator().evaluate_without_reference(
        "NASA reported 42% growth in 2024.",
        source_chunks=[{"text": "NASA reported 42% growth in 2024."}],
        query="NASA reported",
    )

    metrics = result["grounded_metrics"]
    assert metrics["citation_coverage"]["status"] == "unavailable"
    assert metrics["evidence_diversity"]["status"] == "unavailable"


def test_traceable_support_does_not_require_ids_for_unrelated_selected_chunks():
    result = SummaryEvaluator().evaluate_without_reference(
        "NASA reported 42% growth in 2024.",
        source_chunks=[_source_chunks()[0], {"text": "Unrelated appendix text."}],
        query="NASA growth",
    )

    citation = result["grounded_metrics"]["citation_coverage"]
    assert citation["status"] == "available"
    assert citation["details"]["sentence_support"][0]["chunk_id"] == "results-1"


def test_redundant_sentences_warn_without_failing_the_quality_gate():
    result = SummaryEvaluator().evaluate_without_reference(
        "NASA reported 42% growth in 2024. NASA reported 42% growth in 2024.",
        source_chunks=[_source_chunks()[0]],
        query="NASA reported",
    )

    quality = QualityChecker(min_summary_words=1).check(result)

    assert result["grounded_metrics"]["redundancy"]["score"] == 0.0
    assert quality["metric_decisions"]["redundancy"]["decision"] == "warn"
    assert quality["status"] == "WARN"


def test_single_section_multi_chunk_evidence_warns_for_low_diversity():
    source_chunks = [
        {
            "chunk_id": "results-1",
            "text": "NASA reported 42% growth in 2024.",
            "hierarchy": {"section_id": "results"},
        },
        {
            "chunk_id": "results-2",
            "text": "ESA confirmed the outcome after review.",
            "hierarchy": {"section_id": "results"},
        },
    ]
    result = SummaryEvaluator().evaluate_without_reference(
        "NASA reported 42% growth in 2024. ESA confirmed the outcome after review.",
        source_chunks=source_chunks,
        query="NASA ESA outcome",
    )

    quality = QualityChecker(min_summary_words=1).check(result)

    assert result["grounded_metrics"]["evidence_diversity"]["score"] == 0.5
    assert quality["metric_decisions"]["evidence_diversity"]["decision"] == "warn"
    assert quality["status"] == "WARN"
