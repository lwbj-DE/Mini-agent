"""Safe calculator tool using AST whitelisting."""

import ast
import math
import operator
from typing import Any

from .base import BaseTool

# ---------- allowed operations (whitelist) ----------
_ALLOWED_OPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_ALLOWED_NAMES: dict[str, Any] = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "exp": math.exp,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "floor": math.floor,
    "ceil": math.ceil,
    "factorial": math.factorial,
    "gcd": math.gcd,
}


class _SafeEval(ast.NodeVisitor):
    """AST-based safe expression evaluator."""

    def __init__(self) -> None:
        self._result: float | int = 0

    def visit_Expression(self, node: ast.Expression) -> Any:  # noqa: N802
        return self.visit(node.body)

    def visit_BinOp(self, node: ast.BinOp) -> Any:  # noqa: N802
        op_type = type(node.op)
        if op_type not in _ALLOWED_OPS:
            raise ValueError(f"Operator {op_type.__name__} is not allowed")
        left = self.visit(node.left)
        right = self.visit(node.right)
        return _ALLOWED_OPS[op_type](left, right)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:  # noqa: N802
        op_type = type(node.op)
        if op_type not in _ALLOWED_OPS:
            raise ValueError(f"Operator {op_type.__name__} is not allowed")
        return _ALLOWED_OPS[op_type](self.visit(node.operand))

    def visit_Constant(self, node: ast.Constant) -> Any:  # noqa: N802
        if not isinstance(node.value, (int, float)):
            raise ValueError(f"Constant type {type(node.value)} not allowed")
        return node.value

    def visit_Name(self, node: ast.Name) -> Any:  # noqa: N802
        if node.id not in _ALLOWED_NAMES:
            raise ValueError(f"Name '{node.id}' is not allowed")
        return _ALLOWED_NAMES[node.id]

    def visit_Call(self, node: ast.Call) -> Any:  # noqa: N802
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only simple function calls are allowed")
        if node.func.id not in _ALLOWED_NAMES:
            raise ValueError(f"Function '{node.func.id}' is not allowed")
        func = _ALLOWED_NAMES[node.func.id]
        if not callable(func):
            raise ValueError(f"'{node.func.id}' is not callable")
        args = [self.visit(a) for a in node.args]
        return func(*args)

    def generic_visit(self, node: ast.AST) -> Any:
        raise ValueError(f"AST node {type(node).__name__} is not allowed")


def safe_eval(expression: str) -> str:
    """Evaluate a mathematical expression safely.

    Args:
        expression: A string containing a math expression,
            e.g. "2 + 3 * 4", "sqrt(16)", "sin(pi/2)".

    Returns:
        String representation of the numeric result.

    Raises:
        ValueError: If the expression contains disallowed operations.
    """
    # Strip common wrappers and whitespace
    expr = expression.strip().strip("`").strip()
    if expr.lower().startswith("math."):
        expr = expr[5:]
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"Invalid expression syntax: {e}") from e
    evaluator = _SafeEval()
    result = evaluator.visit(tree)
    # Format result nicely
    if isinstance(result, float):
        if result == int(result):
            return str(int(result))
        return f"{result:.10g}"
    return str(result)


class CalculatorTool(BaseTool):
    """Safe mathematical expression evaluator."""

    @property
    def name(self) -> str:
        return "calculator"

    @property
    def description(self) -> str:
        return (
            "Safely evaluate a mathematical expression. "
            "Supports basic arithmetic (+, -, *, /, **, %), "
            "common math functions (sqrt, sin, cos, tan, log, log2, log10, "
            "exp, abs, round, min, max, floor, ceil, factorial, gcd), "
            "and constants (pi, e, tau). "
            "Example expressions: '2 + 3 * 4', 'sqrt(144)', "
            "'sin(pi/2)', 'factorial(5)'."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": (
                        "The mathematical expression to evaluate, "
                        "e.g. '2 + 3 * 4', 'sqrt(144)', 'sin(pi/2)'."
                    ),
                }
            },
            "required": ["expression"],
        }

    def execute(self, expression: str = "", **kwargs: Any) -> str:
        """Evaluate *expression* and return the result."""
        if not expression:
            return "Error: no expression provided"
        try:
            result = safe_eval(expression)
            return result
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Unexpected error evaluating '{expression}': {e}"
