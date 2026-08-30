"""
Run the golden-question evaluation suite against the REAL configured
LLM provider.

    python scripts/run_evaluation.py

Requires: Postgres running + schema indexed (Stage 1/2) and a real
LLM_PROVIDER configured with a working API key (Stage 3) -- this makes
actual model calls for all 50 questions, so it costs real (free-tier)
API quota and takes a minute or two. Results are written to
data/evaluation/results_<timestamp>.json and a summary table is
printed. The README's metrics section is generated FROM this script's
output, never hand-written -- see spec section 22's explicit
requirement that reported metrics come from an actual run.
"""

from __future__ import annotations

import sys
import time

from tabulate import tabulate

from app.evaluation.evaluator import run_evaluation, save_results


def main() -> int:
    print("Running evaluation against golden_questions.json (50 questions)...")
    print("This makes real LLM calls -- expect this to take 1-2 minutes.\n")

    t0 = time.time()
    results, metrics = run_evaluation()
    elapsed = time.time() - t0

    output_path = f"data/evaluation/results_{int(time.time())}.json"
    save_results(results, metrics, output_path)

    print(f"Completed {metrics.total_questions} questions in {elapsed:.1f}s\n")

    print("=== Aggregate metrics ===")
    metric_rows = [
        ["SQL Validity Rate", f"{metrics.sql_validity_rate:.0%}"],
        ["Execution Accuracy", f"{metrics.execution_accuracy:.0%}"],
        ["Guardrail Detection Rate", f"{metrics.guardrail_detection_rate:.0%}"],
        ["False Positive Rate", f"{metrics.false_positive_rate:.0%}"],
        ["Blocked Unsafe Query Rate", f"{metrics.blocked_unsafe_query_rate:.0%}"],
        ["Average Latency", f"{metrics.average_latency_ms:.0f} ms"],
    ]
    print(tabulate(metric_rows, headers=["Metric", "Value"], tablefmt="github"))

    mismatches = [r for r in results if not r["matched_expectation"]]
    if mismatches:
        print(f"\n=== {len(mismatches)} question(s) did not match expected behavior ===")
        rows = [
            [r["id"], r["category"], r["expected_behavior"], r["actual_status"], r["question"][:50]]
            for r in mismatches
        ]
        print(tabulate(rows, headers=["ID", "Category", "Expected", "Actual", "Question"], tablefmt="github"))
    else:
        print("\nAll questions matched their expected behavior.")

    print(f"\nFull results written to {output_path}")
    return 0 if not mismatches else 1


if __name__ == "__main__":
    sys.exit(main())
