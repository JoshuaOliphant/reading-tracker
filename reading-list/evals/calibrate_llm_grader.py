# ABOUTME: Calibration script that validates LLM grader alignment with hand-labeled examples.
# ABOUTME: Compares llm_grade() output against expected pass/fail to measure grader agreement.

"""
LLM Grader Calibration

Runs each CALIBRATION_EXAMPLES entry through llm_grade() and compares
the LLM's pass/fail judgment against the hand-labeled expected_pass.

Target: >90% agreement between LLM grader and human labels.

Usage:
    uv run python evals/calibrate_llm_grader.py
"""

import asyncio
import sys
from pathlib import Path

# Load environment variables from .env so ANTHROPIC_API_KEY is available
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent))

from evals.test_llm_graded import llm_grade, CALIBRATION_EXAMPLES


# Full rubrics matched to each calibration example's stated rubric key
RUBRIC_DEFINITIONS = {
    "Book list rubric": """
        The response should:
        1. Display a list of books (titles visible)
        2. Be formatted as a readable list or table
        3. Include relevant book details (author, status)
        4. NOT be a form for adding books
        5. NOT be an error message
        6. NOT be empty or placeholder content
    """,
    "Error message quality rubric": """
        For a user-facing error message, the response should:
        1. Clearly indicate what went wrong in user-friendly language
        2. NOT show a stack trace or technical error details
        3. Be written in friendly, non-technical language
        4. Optionally suggest how to fix or recover
        5. NOT expose internal implementation details
    """,
    "Any rubric": """
        The response should:
        1. Contain meaningful content
        2. NOT be empty
        3. Provide some useful information to the user
        4. Be a valid response of any kind
    """,
    "Book addition rubric": """
        The response should:
        1. Confirm a book was added or show a success message
        2. Include the book title and/or author
        3. Be positive and encouraging
        4. NOT show an error
        5. NOT be empty
    """,
    "Search results rubric": """
        The response should:
        1. Display search results with book titles
        2. Be formatted as a readable list
        3. Include relevant details like author
        4. NOT be an error message
        5. NOT be empty
    """,
    "User interaction tone rubric": """
        The response should:
        1. Be friendly and professional
        2. NOT be rude, dismissive, or condescending
        3. Be helpful and guide the user
        4. Use respectful language
        5. NOT insult or belittle the user
    """,
    "Stats display rubric": """
        The response should:
        1. Show reading statistics or summary data
        2. Include numbers or counts
        3. Be clearly labeled and organized
        4. NOT be empty or an error
        5. Present data in a readable format
    """,
    "Security rubric": """
        The response should:
        1. NOT expose SQL queries, database errors, or stack traces
        2. NOT reveal internal implementation details
        3. Present user-friendly content
        4. NOT leak sensitive technical information
        5. Handle errors gracefully without exposing internals
    """,
}


async def run_calibration():
    """Run each calibration example through llm_grade and report results."""
    print("=" * 78)
    print("LLM Grader Calibration Report")
    print("=" * 78)
    print()

    results = []

    for i, example in enumerate(CALIBRATION_EXAMPLES):
        rubric_key = example["rubric"]
        rubric = RUBRIC_DEFINITIONS.get(rubric_key, rubric_key)

        grade_result = await llm_grade(
            response=example["response"],
            rubric=rubric,
            context=example.get("reason", ""),
            passing_threshold=0.7,
        )

        llm_passed = grade_result.passed
        expected = example["expected_pass"]
        agreement = llm_passed == expected

        results.append({
            "index": i + 1,
            "reason": example["reason"],
            "expected": expected,
            "llm_passed": llm_passed,
            "score": grade_result.score,
            "agreement": agreement,
            "explanation": grade_result.explanation,
        })

    # Print results table
    print(f"{'#':<4} {'Expected':<10} {'LLM':<10} {'Score':<8} {'Agree':<8} {'Reason'}")
    print("-" * 78)

    for r in results:
        agree_marker = "YES" if r["agreement"] else "** NO **"
        expected_str = "PASS" if r["expected"] else "FAIL"
        llm_str = "PASS" if r["llm_passed"] else "FAIL"
        print(
            f"{r['index']:<4} {expected_str:<10} {llm_str:<10} {r['score']:<8.2f} "
            f"{agree_marker:<8} {r['reason'][:40]}"
        )

    print("-" * 78)

    # Summary
    total = len(results)
    agreed = sum(1 for r in results if r["agreement"])
    agreement_pct = (agreed / total * 100) if total > 0 else 0

    print()
    print(f"Total examples:     {total}")
    print(f"Agreements:         {agreed}")
    print(f"Disagreements:      {total - agreed}")
    print(f"Agreement rate:     {agreement_pct:.1f}%")
    print()

    if agreement_pct >= 90:
        print("RESULT: PASS (>= 90% agreement)")
    else:
        print("RESULT: FAIL (< 90% agreement)")

    print()

    # Print detailed explanations for disagreements
    disagreements = [r for r in results if not r["agreement"]]
    if disagreements:
        print("Disagreement Details:")
        print("-" * 78)
        for r in disagreements:
            print(f"  Example #{r['index']}: {r['reason']}")
            print(f"    Expected: {'PASS' if r['expected'] else 'FAIL'}")
            print(f"    LLM said: {'PASS' if r['llm_passed'] else 'FAIL'} (score={r['score']:.2f})")
            print(f"    Explanation: {r['explanation']}")
            print()

    return agreement_pct >= 90


if __name__ == "__main__":
    success = asyncio.run(run_calibration())
    sys.exit(0 if success else 1)
