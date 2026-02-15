# ABOUTME: Dataset definitions for pydantic-evals based agent evaluation.
# ABOUTME: Exports Case, Dataset, and pre-defined CRUD test datasets.

"""
Eval Datasets

Defines test cases as structured data using pydantic-evals patterns.
Cases include inputs, expected outputs, and evaluator configurations.
"""

from .crud_cases import CRUD_DATASET, ADD_BOOK_CASES, LIST_BOOK_CASES

__all__ = ["CRUD_DATASET", "ADD_BOOK_CASES", "LIST_BOOK_CASES"]
