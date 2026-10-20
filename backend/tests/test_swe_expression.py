"""Deterministic SWD expression evaluation."""

from __future__ import annotations

import pytest

from app.swe.errors import SwdExpressionError
from app.swe.expression import evaluate_expression


def test_lt_three_less_than_five_is_true() -> None:
    result = evaluate_expression({"lt": [{"const": 3}, {"const": 5}]}, {})
    assert result is True


def test_missing_value_is_typed_error() -> None:
    with pytest.raises(SwdExpressionError, match="missing value"):
        evaluate_expression({"var": "$.run.steps_used"}, {})


def test_null_is_not_a_number() -> None:
    with pytest.raises(SwdExpressionError, match="requires numbers"):
        evaluate_expression({"lt": [{"const": None}, {"const": 5}]}, {})


def test_boolean_is_not_compared_as_number() -> None:
    with pytest.raises(SwdExpressionError, match="requires numbers"):
        evaluate_expression({"lt": [{"const": True}, {"const": 1}]}, {})


def test_var_default_is_used_when_missing() -> None:
    result = evaluate_expression({"var": "$.missing", "default": 7}, {})
    assert result == 7


def test_exists_is_false_for_missing_path() -> None:
    assert evaluate_expression({"exists": "$.nope"}, {"run": {}}) is False


def test_string_expression_is_rejected() -> None:
    with pytest.raises(SwdExpressionError, match="non-empty object"):
        evaluate_expression("3 < 5", {})


def test_eq_rejects_mixed_types() -> None:
    with pytest.raises(SwdExpressionError, match="matching JSON types"):
        evaluate_expression({"eq": [{"const": 1}, {"const": "1"}]}, {})


def test_in_does_not_treat_true_as_one() -> None:
    assert evaluate_expression({"in": [{"const": True}, {"const": [1]}]}, {}) is False
    assert evaluate_expression({"in": [{"const": 1}, {"const": [True]}]}, {}) is False
    assert evaluate_expression({"in": [{"const": True}, {"const": [True]}]}, {}) is True
    assert evaluate_expression({"in": [{"const": 1}, {"const": [1]}]}, {}) is True
