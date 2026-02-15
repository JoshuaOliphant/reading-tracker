# ABOUTME: Reusable grader functions for evaluating agent behavior.
# ABOUTME: Provides state checks, tool verification, HTML validation, and partial credit scoring.

"""
Reusable Graders for Agent Evals

Implements different grading strategies:
- StateCheck: Verify database state changes
- ToolWasCalled: Verify specific tools were invoked
- HTMLContains: Check HTML response content
- PartialCredit: Score multi-step tasks with intermediate credit
- NegativeCheck: Verify agent did NOT do something

Usage:
    grader = StateCheck("books", expected_count=3)
    result = await grader.grade(transcript)
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from evals.transcript import TrialTranscript


@dataclass
class GradeResult:
    """Result of a grading operation."""
    passed: bool
    score: float  # 0.0 to 1.0
    explanation: str
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return not self.passed


class Grader(ABC):
    """Abstract base class for graders."""

    @abstractmethod
    async def grade(self, transcript: TrialTranscript) -> GradeResult:
        """Grade the transcript and return a result."""
        pass


class StateCheck(Grader):
    """
    Verify database state after agent execution.

    This is the gold standard for agent evals - don't trust the agent's
    UI claims, verify actual database state.
    """

    def __init__(
        self,
        table: str,
        expected_count: int | None = None,
        count_change: int | None = None,
        field_check: dict[str, Any] | None = None,
    ):
        """
        Initialize state checker.

        Args:
            table: Table name to check (e.g., "books")
            expected_count: Exact count expected after operation
            count_change: Expected change in count (e.g., +1 for create)
            field_check: Dict of field→value to verify exists
        """
        self.table = table
        self.expected_count = expected_count
        self.count_change = count_change
        self.field_check = field_check or {}

    async def grade(self, transcript: TrialTranscript) -> GradeResult:
        if not transcript.state_after:
            return GradeResult(
                passed=False,
                score=0.0,
                explanation="No state_after snapshot available",
            )

        # Get the appropriate data based on table
        if self.table == "books":
            data = transcript.state_after.books
        else:
            return GradeResult(
                passed=False,
                score=0.0,
                explanation=f"Unknown table: {self.table}",
            )

        actual_count = len(data)
        details = {"actual_count": actual_count, "data": data}

        # Check expected count
        if self.expected_count is not None:
            if actual_count != self.expected_count:
                return GradeResult(
                    passed=False,
                    score=0.0,
                    explanation=f"Expected {self.expected_count} {self.table}, got {actual_count}",
                    details=details,
                )

        # Check count change
        if self.count_change is not None and transcript.state_before:
            before_count = len(transcript.state_before.books) if self.table == "books" else 0
            actual_change = actual_count - before_count

            if actual_change != self.count_change:
                return GradeResult(
                    passed=False,
                    score=0.0,
                    explanation=f"Expected count change of {self.count_change}, got {actual_change}",
                    details=details,
                )

        # Check specific field values
        if self.field_check:
            for field_name, expected_value in self.field_check.items():
                found = any(
                    str(item.get(field_name, "")).lower() == str(expected_value).lower()
                    for item in data
                )
                if not found:
                    return GradeResult(
                        passed=False,
                        score=0.0,
                        explanation=f"No record with {field_name}='{expected_value}' found",
                        details=details,
                    )

        return GradeResult(
            passed=True,
            score=1.0,
            explanation="State check passed",
            details=details,
        )


class ToolWasCalled(Grader):
    """Verify that a specific tool was called during execution."""

    def __init__(
        self,
        tool_name: str,
        min_calls: int = 1,
        max_calls: int | None = None,
        arg_check: dict[str, Any] | None = None,
    ):
        """
        Initialize tool call checker.

        Args:
            tool_name: Name of the tool to check (e.g., "create_book")
            min_calls: Minimum number of times tool should be called
            max_calls: Maximum calls (None for unlimited)
            arg_check: Dict of arg→value to verify in at least one call
        """
        self.tool_name = tool_name
        self.min_calls = min_calls
        self.max_calls = max_calls
        self.arg_check = arg_check or {}

    async def grade(self, transcript: TrialTranscript) -> GradeResult:
        matching_calls = [
            tc for tc in transcript.tool_calls
            if tc.name == self.tool_name
        ]

        call_count = len(matching_calls)
        details = {
            "tool_name": self.tool_name,
            "call_count": call_count,
            "calls": [tc.to_dict() for tc in matching_calls],
        }

        # Check minimum calls
        if call_count < self.min_calls:
            return GradeResult(
                passed=False,
                score=0.0,
                explanation=f"Expected at least {self.min_calls} call(s) to {self.tool_name}, got {call_count}",
                details=details,
            )

        # Check maximum calls
        if self.max_calls is not None and call_count > self.max_calls:
            return GradeResult(
                passed=False,
                score=0.0,
                explanation=f"Expected at most {self.max_calls} call(s) to {self.tool_name}, got {call_count}",
                details=details,
            )

        # Check argument values if specified
        if self.arg_check:
            arg_match_found = False
            for tc in matching_calls:
                args = tc.args.get("kwargs", {})
                if all(
                    str(args.get(k, "")).lower() == str(v).lower()
                    for k, v in self.arg_check.items()
                ):
                    arg_match_found = True
                    break

            if not arg_match_found:
                return GradeResult(
                    passed=False,
                    score=0.0,
                    explanation=f"No call to {self.tool_name} with args {self.arg_check}",
                    details=details,
                )

        return GradeResult(
            passed=True,
            score=1.0,
            explanation=f"Tool {self.tool_name} called {call_count} time(s)",
            details=details,
        )


class ToolNotCalled(Grader):
    """Verify that a specific tool was NOT called (for negative tests)."""

    def __init__(self, tool_name: str):
        self.tool_name = tool_name

    async def grade(self, transcript: TrialTranscript) -> GradeResult:
        matching_calls = [
            tc for tc in transcript.tool_calls
            if tc.name == self.tool_name
        ]

        if matching_calls:
            return GradeResult(
                passed=False,
                score=0.0,
                explanation=f"Tool {self.tool_name} should NOT have been called, but was called {len(matching_calls)} time(s)",
                details={"calls": [tc.to_dict() for tc in matching_calls]},
            )

        return GradeResult(
            passed=True,
            score=1.0,
            explanation=f"Tool {self.tool_name} correctly not called",
        )


class HTMLContains(Grader):
    """Check that HTML response contains expected patterns."""

    def __init__(
        self,
        patterns: list[str],
        require_all: bool = True,
        case_sensitive: bool = False,
    ):
        """
        Initialize HTML checker.

        Args:
            patterns: List of strings or regex patterns to find
            require_all: If True, all patterns must match. If False, any one.
            case_sensitive: Whether matching is case-sensitive
        """
        self.patterns = patterns
        self.require_all = require_all
        self.case_sensitive = case_sensitive

    async def grade(self, transcript: TrialTranscript) -> GradeResult:
        html = transcript.html_response
        if not self.case_sensitive:
            html = html.lower()

        matches = []
        for pattern in self.patterns:
            search_pattern = pattern if self.case_sensitive else pattern.lower()
            if search_pattern in html:
                matches.append(pattern)

        match_count = len(matches)
        total = len(self.patterns)
        details = {
            "matched_patterns": matches,
            "missing_patterns": [p for p in self.patterns if p not in matches],
            "html_length": len(transcript.html_response),
        }

        if self.require_all:
            if match_count == total:
                return GradeResult(
                    passed=True,
                    score=1.0,
                    explanation=f"All {total} patterns found",
                    details=details,
                )
            else:
                return GradeResult(
                    passed=False,
                    score=match_count / total if total > 0 else 0.0,
                    explanation=f"Only {match_count}/{total} patterns found",
                    details=details,
                )
        else:
            # Any one pattern is sufficient
            if match_count > 0:
                return GradeResult(
                    passed=True,
                    score=1.0,
                    explanation=f"Found {match_count} matching pattern(s)",
                    details=details,
                )
            else:
                return GradeResult(
                    passed=False,
                    score=0.0,
                    explanation="No patterns matched",
                    details=details,
                )


class HTMLNotContains(Grader):
    """Check that HTML response does NOT contain certain patterns (for negative tests)."""

    def __init__(self, patterns: list[str], case_sensitive: bool = False):
        self.patterns = patterns
        self.case_sensitive = case_sensitive

    async def grade(self, transcript: TrialTranscript) -> GradeResult:
        html = transcript.html_response
        if not self.case_sensitive:
            html = html.lower()

        found_patterns = []
        for pattern in self.patterns:
            search_pattern = pattern if self.case_sensitive else pattern.lower()
            if search_pattern in html:
                found_patterns.append(pattern)

        if found_patterns:
            return GradeResult(
                passed=False,
                score=0.0,
                explanation=f"Unexpected patterns found: {found_patterns}",
                details={"found_patterns": found_patterns},
            )

        return GradeResult(
            passed=True,
            score=1.0,
            explanation="No forbidden patterns found",
        )


@dataclass
class Step:
    """A single step in a multi-step task."""
    name: str
    grader: Grader
    weight: float = 1.0


class PartialCredit(Grader):
    """
    Score multi-step tasks with partial credit for intermediate successes.

    This is crucial for complex agent tasks where we want to know
    "how far did the agent get" rather than just pass/fail.
    """

    def __init__(self, steps: list[Step]):
        """
        Initialize partial credit grader.

        Args:
            steps: List of Step objects with name, grader, and weight
        """
        self.steps = steps
        total_weight = sum(s.weight for s in steps)
        # Normalize weights to sum to 1.0
        for step in self.steps:
            step.weight = step.weight / total_weight if total_weight > 0 else 0

    async def grade(self, transcript: TrialTranscript) -> GradeResult:
        step_results = []
        total_score = 0.0
        all_passed = True

        for step in self.steps:
            result = await step.grader.grade(transcript)
            step_results.append({
                "name": step.name,
                "passed": result.passed,
                "score": result.score,
                "weight": step.weight,
                "weighted_score": result.score * step.weight,
                "explanation": result.explanation,
            })

            total_score += result.score * step.weight
            if not result.passed:
                all_passed = False

        return GradeResult(
            passed=all_passed,
            score=total_score,
            explanation=f"Completed {sum(1 for s in step_results if s['passed'])}/{len(self.steps)} steps ({total_score:.1%})",
            details={"steps": step_results},
        )


class NoError(Grader):
    """Verify that no error occurred during execution."""

    async def grade(self, transcript: TrialTranscript) -> GradeResult:
        if transcript.error:
            return GradeResult(
                passed=False,
                score=0.0,
                explanation=f"Error occurred: {transcript.error}",
                details={"error": transcript.error},
            )

        return GradeResult(
            passed=True,
            score=1.0,
            explanation="No errors",
        )


class ResponseNotEmpty(Grader):
    """Verify that a non-empty response was generated."""

    def __init__(self, min_length: int = 10):
        self.min_length = min_length

    async def grade(self, transcript: TrialTranscript) -> GradeResult:
        length = len(transcript.html_response)

        if length < self.min_length:
            return GradeResult(
                passed=False,
                score=0.0,
                explanation=f"Response too short ({length} < {self.min_length})",
                details={"length": length, "min_required": self.min_length},
            )

        return GradeResult(
            passed=True,
            score=1.0,
            explanation=f"Response length: {length}",
            details={"length": length},
        )


class CompositeGrader(Grader):
    """Combine multiple graders with AND/OR logic."""

    def __init__(self, graders: list[Grader], require_all: bool = True):
        """
        Args:
            graders: List of graders to combine
            require_all: If True, all must pass (AND). If False, any one (OR).
        """
        self.graders = graders
        self.require_all = require_all

    async def grade(self, transcript: TrialTranscript) -> GradeResult:
        results = []
        for grader in self.graders:
            result = await grader.grade(transcript)
            results.append(result)

        passed_count = sum(1 for r in results if r.passed)
        total = len(results)
        avg_score = sum(r.score for r in results) / total if total > 0 else 0

        details = {
            "results": [
                {"passed": r.passed, "score": r.score, "explanation": r.explanation}
                for r in results
            ],
            "passed_count": passed_count,
            "total": total,
        }

        if self.require_all:
            all_passed = passed_count == total
            return GradeResult(
                passed=all_passed,
                score=avg_score,
                explanation=f"{passed_count}/{total} graders passed",
                details=details,
            )
        else:
            any_passed = passed_count > 0
            return GradeResult(
                passed=any_passed,
                score=1.0 if any_passed else 0.0,
                explanation=f"{passed_count}/{total} graders passed (need 1)",
                details=details,
            )
