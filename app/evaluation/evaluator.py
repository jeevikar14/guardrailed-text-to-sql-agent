"""
Evaluation harness runner (spec section 22).

Runs every question in data/evaluation/golden_questions.json through
the REAL agent graph (app.agent.runner.run_agent) -- this calls the
actually-configured LLM provider, not a stub. scripts/run_evaluation.py
is the CLI entry point; this module is the reusable logic.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from app.agent.runner import run_agent
from app.evaluation.metrics import MetricsSummary, compute_metrics

DEFAULT_GOLDEN_PATH = "data/evaluation/golden_questions.json"


def load_golden_questions(path: str = DEFAULT_GOLDEN_PATH) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_question(question_spec: dict) -> dict:
    """Run one golden question through the real agent and record what actually happened."""
    t0 = time.monotonic()
    state = run_agent(question_spec["question"])
    latency_ms = int((time.monotonic() - t0) * 1000)

    return {
        "id": question_spec["id"],
        "question": question_spec["question"],
        "category": question_spec.get("category"),
        "expected_behavior": question_spec["expected_behavior"],
        "expected_tables": question_spec.get("expected_tables", []),
        "actual_status": state["status"],
        "sql_generated": state.get("generated_sql") is not None,
        "actual_tables": (state.get("sql_metadata") or {}).get("tables_used", []),
        "blocked_guard": state.get("blocked_guard"),
        "repair_attempted": state.get("repair_attempted", False),
        "latency_ms": latency_ms,
        "matched_expectation": _matched_expectation(question_spec["expected_behavior"], state["status"]),
    }


def _matched_expectation(expected_behavior: str, actual_status: str) -> bool:
    if expected_behavior == "allow":
        return actual_status == "SUCCESS"
    if expected_behavior == "block":
        return actual_status == "BLOCKED"
    return False


def run_evaluation(golden_path: str = DEFAULT_GOLDEN_PATH) -> tuple[list[dict], MetricsSummary]:
    """Run the full golden set and return (per-question results, aggregate metrics)."""
    questions = load_golden_questions(golden_path)
    results = [evaluate_question(q) for q in questions]
    metrics = compute_metrics(results)
    return results, metrics


def save_results(results: list[dict], metrics: MetricsSummary, output_path: str) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metrics": {
            "total_questions": metrics.total_questions,
            "sql_validity_rate": metrics.sql_validity_rate,
            "execution_accuracy": metrics.execution_accuracy,
            "guardrail_detection_rate": metrics.guardrail_detection_rate,
            "false_positive_rate": metrics.false_positive_rate,
            "blocked_unsafe_query_rate": metrics.blocked_unsafe_query_rate,
            "average_latency_ms": metrics.average_latency_ms,
        },
        "results": results,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
