"""Güvenli hesap motoru — eval() yok, AST tabanlı."""

from __future__ import annotations

import ast
import operator
from typing import Union

# Desteklenen operatörler — yalnızca temel aritmetik
_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}


class UnsafeExpressionError(ValueError):
    """Desteklenmeyen veya güvensiz ifade hatası."""


def safe_eval(expr: str) -> Union[int, float]:
    """Aritmetik ifadeyi AST ile güvenli biçimde değerlendirir.

    Yalnızca sayısal sabitler ve temel aritmetik operatörleri
    (+, -, *, /, %, **) destekler. eval() kullanmaz.

    Args:
        expr: Değerlendirilecek matematiksel ifade (ör. "2 + 3 * 4").

    Returns:
        Hesaplama sonucu (int veya float).

    Raises:
        UnsafeExpressionError: Desteklenmeyen ifade türü.
        ZeroDivisionError: Sıfıra bölme.
        SyntaxError: Geçersiz ifade sözdizimi.
    """
    def _eval(node: ast.AST) -> Union[int, float]:
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)):
                raise UnsafeExpressionError(f"Desteklenmeyen sabit: {node.value}")
            return node.value
        if isinstance(node, ast.BinOp):
            op = _SAFE_OPS.get(type(node.op))
            if not op:
                raise UnsafeExpressionError(f"Desteklenmeyen operatör: {type(node.op).__name__}")
            left, right = _eval(node.left), _eval(node.right)
            if isinstance(node.op, ast.Div) and right == 0:
                raise ZeroDivisionError("Sıfıra bölme hatası")
            return op(left, right)
        if isinstance(node, ast.UnaryOp):
            op = _SAFE_OPS.get(type(node.op))
            if not op:
                raise UnsafeExpressionError(f"Desteklenmeyen unary: {type(node.op).__name__}")
            return op(_eval(node.operand))
        raise UnsafeExpressionError(f"Desteklenmeyen ifade: {type(node).__name__}")

    tree = ast.parse(expr, mode="eval")
    return _eval(tree.body)
