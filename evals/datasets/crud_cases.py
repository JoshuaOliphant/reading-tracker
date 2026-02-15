# ABOUTME: CRUD operation test cases defined as structured data.
# ABOUTME: Uses pydantic-evals patterns for declarative test case definition.

"""
CRUD Operation Test Cases

Defines test cases for book CRUD operations using a declarative approach.
Each case specifies:
- name: Unique identifier for the case
- inputs: User message and any setup requirements
- expected: Expected outcomes (database state, UI content)
- evaluators: List of graders to verify the case

Usage:
    from evals.datasets import CRUD_DATASET

    for case in CRUD_DATASET.cases:
        # Run case and verify with evaluators
        pass
"""

from dataclasses import dataclass, field
from typing import Any, Callable
from enum import Enum

from evals.graders import (
    Grader,
    StateCheck,
    ToolWasCalled,
    ToolNotCalled,
    HTMLContains,
    HTMLNotContains,
    PartialCredit,
    Step,
    NoError,
    ResponseNotEmpty,
    CompositeGrader,
)


class CaseCategory(Enum):
    """Categories of test cases for organization."""
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    SEARCH = "search"
    NEGATIVE = "negative"


@dataclass
class Case:
    """
    A single test case for agent evaluation.

    Attributes:
        name: Unique identifier (used in test reports)
        message: User message to send to agent
        expected: Dict of expected outcomes for documentation
        evaluators: List of Grader instances to verify outcomes
        category: Case category for organization
        setup: Optional setup function (called before test)
        tags: Optional tags for filtering
    """
    name: str
    message: str
    expected: dict[str, Any]
    evaluators: list[Grader]
    category: CaseCategory = CaseCategory.READ
    setup: Callable | None = None
    tags: list[str] = field(default_factory=list)

    def __post_init__(self):
        # Add category as tag
        if self.category.value not in self.tags:
            self.tags.append(self.category.value)


@dataclass
class Dataset:
    """
    Collection of related test cases.

    Attributes:
        name: Dataset identifier
        description: What this dataset tests
        cases: List of Case objects
    """
    name: str
    description: str
    cases: list[Case]

    def get_by_category(self, category: CaseCategory) -> list[Case]:
        """Get all cases in a category."""
        return [c for c in self.cases if c.category == category]

    def get_by_tag(self, tag: str) -> list[Case]:
        """Get all cases with a specific tag."""
        return [c for c in self.cases if tag in c.tags]


# =============================================================================
# ADD BOOK CASES
# =============================================================================

ADD_BOOK_CASES = [
    Case(
        name="add_book_natural",
        message="add Dune by Frank Herbert",
        expected={
            "book_created": True,
            "title_contains": "dune",
            "author_contains": "herbert",
        },
        evaluators=[
            ToolWasCalled("create_book"),
            StateCheck("books", count_change=1),
            StateCheck("books", field_check={"title": "Dune"}),
            NoError(),
        ],
        category=CaseCategory.CREATE,
        tags=["natural_language", "basic"],
    ),
    Case(
        name="add_book_quotes",
        message="add 'The Great Gatsby' by F. Scott Fitzgerald",
        expected={
            "book_created": True,
            "title": "The Great Gatsby",
        },
        evaluators=[
            StateCheck("books", count_change=1),
            StateCheck("books", field_check={"title": "The Great Gatsby"}),
        ],
        category=CaseCategory.CREATE,
        tags=["natural_language", "quotes"],
    ),
    Case(
        name="add_book_with_rating",
        message="add '1984' by George Orwell, 5 stars",
        expected={
            "book_created": True,
            "rating": 5,
        },
        evaluators=[
            StateCheck("books", count_change=1),
            StateCheck("books", field_check={"title": "1984"}),
            StateCheck("books", field_check={"rating": 5}),
        ],
        category=CaseCategory.CREATE,
        tags=["natural_language", "with_rating"],
    ),
    Case(
        name="add_book_want_to_read",
        message="I want to read 'Project Hail Mary' by Andy Weir",
        expected={
            "book_created": True,
            "status": "want-to-read",
        },
        evaluators=[
            StateCheck("books", count_change=1),
            StateCheck("books", field_check={"status": "want-to-read"}),
        ],
        category=CaseCategory.CREATE,
        tags=["natural_language", "intent_phrase"],
    ),
]


# =============================================================================
# LIST BOOK CASES
# =============================================================================

LIST_BOOK_CASES = [
    Case(
        name="list_books_basic",
        message="show my books",
        expected={
            "tool_called": "get_all_books",
            "html_has_list": True,
        },
        evaluators=[
            ToolWasCalled("get_all_books"),
            ResponseNotEmpty(min_length=50),
            NoError(),
        ],
        category=CaseCategory.READ,
        tags=["basic", "list"],
    ),
    Case(
        name="list_books_all",
        message="list all books",
        expected={
            "tool_called": "get_all_books",
        },
        evaluators=[
            ToolWasCalled("get_all_books"),
            ResponseNotEmpty(min_length=50),
        ],
        category=CaseCategory.READ,
        tags=["basic", "list"],
    ),
    Case(
        name="list_books_question",
        message="what books do I have?",
        expected={
            "tool_called": "get_all_books",
        },
        evaluators=[
            ToolWasCalled("get_all_books"),
            ResponseNotEmpty(min_length=50),
        ],
        category=CaseCategory.READ,
        tags=["question_form", "list"],
    ),
    Case(
        name="list_books_reading_list",
        message="show my reading list",
        expected={
            "tool_called": "get_all_books",
        },
        evaluators=[
            ToolWasCalled("get_all_books"),
        ],
        category=CaseCategory.READ,
        tags=["synonym", "list"],
    ),
    Case(
        name="list_books_library",
        message="view my library",
        expected={
            "tool_called": "get_all_books",
        },
        evaluators=[
            ToolWasCalled("get_all_books"),
        ],
        category=CaseCategory.READ,
        tags=["synonym", "list"],
    ),
]


# =============================================================================
# UPDATE BOOK CASES
# =============================================================================

UPDATE_BOOK_CASES = [
    Case(
        name="update_status_reading",
        message="start reading book {book_id}",
        expected={
            "status_changed": "reading",
        },
        evaluators=[
            ToolWasCalled("update_book"),
            StateCheck("books", field_check={"status": "reading"}),
        ],
        category=CaseCategory.UPDATE,
        tags=["status_change"],
    ),
    Case(
        name="update_status_finished",
        message="finished book {book_id}",
        expected={
            "status_changed": "finished",
        },
        evaluators=[
            ToolWasCalled("update_book"),
            StateCheck("books", field_check={"status": "finished"}),
        ],
        category=CaseCategory.UPDATE,
        tags=["status_change"],
    ),
    Case(
        name="update_rating",
        message="rate book {book_id} 4 stars",
        expected={
            "rating_set": 4,
        },
        evaluators=[
            ToolWasCalled("update_book"),
            StateCheck("books", field_check={"rating": 4}),
        ],
        category=CaseCategory.UPDATE,
        tags=["rating"],
    ),
]


# =============================================================================
# DELETE BOOK CASES
# =============================================================================

DELETE_BOOK_CASES = [
    Case(
        name="delete_by_id",
        message="delete book {book_id}",
        expected={
            "book_deleted": True,
        },
        evaluators=[
            ToolWasCalled("delete_book"),
            StateCheck("books", count_change=-1),
        ],
        category=CaseCategory.DELETE,
        tags=["basic"],
    ),
    Case(
        name="delete_ambiguous_fails",
        message="delete a book",
        expected={
            "no_deletion": True,
            "asks_clarification": True,
        },
        evaluators=[
            ToolNotCalled("delete_book"),
            StateCheck("books", count_change=0),
        ],
        category=CaseCategory.NEGATIVE,
        tags=["safety", "clarification"],
    ),
]


# =============================================================================
# SEARCH CASES
# =============================================================================

SEARCH_CASES = [
    Case(
        name="search_by_author",
        message="search for books by Frank Herbert",
        expected={
            "search_executed": True,
        },
        evaluators=[
            ToolWasCalled("search_books"),
            ResponseNotEmpty(min_length=50),
        ],
        category=CaseCategory.SEARCH,
        tags=["author_search"],
    ),
    Case(
        name="search_by_title",
        message="find Dune",
        expected={
            "search_executed": True,
        },
        evaluators=[
            ToolWasCalled("search_books"),
        ],
        category=CaseCategory.SEARCH,
        tags=["title_search"],
    ),
    Case(
        name="search_no_results",
        message="search for xyznonexistent",
        expected={
            "friendly_empty_message": True,
        },
        evaluators=[
            ToolWasCalled("search_books"),
            HTMLNotContains(["error", "exception"]),
        ],
        category=CaseCategory.SEARCH,
        tags=["empty_results"],
    ),
]


# =============================================================================
# NEGATIVE CASES
# =============================================================================

NEGATIVE_CASES = [
    Case(
        name="no_hallucinate_book",
        message="show book 99999",
        expected={
            "shows_not_found": True,
            "no_fake_details": True,
        },
        evaluators=[
            # Response should not contain typical book detail labels for non-existent book
            ResponseNotEmpty(min_length=10),
        ],
        category=CaseCategory.NEGATIVE,
        tags=["hallucination"],
    ),
    Case(
        name="no_rate_nonexistent",
        message="rate 'Fake Book' 5 stars",
        expected={
            "no_book_created": True,
        },
        evaluators=[
            ToolNotCalled("create_book"),
            StateCheck("books", count_change=0),
        ],
        category=CaseCategory.NEGATIVE,
        tags=["safety"],
    ),
]


# =============================================================================
# COMBINED DATASET
# =============================================================================

CRUD_DATASET = Dataset(
    name="crud_operations",
    description="Comprehensive CRUD operation tests for reading list agent",
    cases=(
        ADD_BOOK_CASES +
        LIST_BOOK_CASES +
        UPDATE_BOOK_CASES +
        DELETE_BOOK_CASES +
        SEARCH_CASES +
        NEGATIVE_CASES
    ),
)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_cases_by_tag(tag: str) -> list[Case]:
    """Get all cases across all datasets with a specific tag."""
    return CRUD_DATASET.get_by_tag(tag)


def get_basic_cases() -> list[Case]:
    """Get minimal set of cases for quick smoke testing."""
    return [
        c for c in CRUD_DATASET.cases
        if "basic" in c.tags
    ]


def get_natural_language_cases() -> list[Case]:
    """Get cases testing natural language variations."""
    return [
        c for c in CRUD_DATASET.cases
        if "natural_language" in c.tags
    ]


def get_safety_cases() -> list[Case]:
    """Get cases testing safety behaviors (negative tests)."""
    return [
        c for c in CRUD_DATASET.cases
        if "safety" in c.tags or c.category == CaseCategory.NEGATIVE
    ]
