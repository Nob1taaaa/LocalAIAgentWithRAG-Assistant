"""Allowlisted, bounded tools available to the local assistant."""

from __future__ import annotations

import ast
import math
import operator

from langchain_core.tools import tool

from agent_state import log_event
from vector import list_sources, retrieve

MAX_QUERY_LENGTH = 1000
MAX_TOOL_ARGUMENTS = 500


def _source_label(metadata: dict) -> str:
    source = str(metadata.get("source_name", "uploaded source"))
    if metadata.get("page") is not None:
        return f"{source}, page {metadata['page']}"
    if metadata.get("row") is not None:
        return f"{source}, row {metadata['row']}"
    return source


def make_tools(workspace: str, used_source_labels: set[str], retrieval_limit: int = 5):
    """Create read-only tools scoped to the active workspace."""

    @tool
    def search_knowledge_base(query: str) -> str:
        """Search uploaded documents for relevant passages. Use for questions about the user's files or projects."""
        query = query.strip()
        if not query or len(query) > MAX_QUERY_LENGTH:
            log_event("search_knowledge_base", {"query_length": len(query)}, "rejected", "Query must be 1 to 1000 characters")
            return "Search rejected: query must contain 1 to 1000 characters."
        try:
            documents = retrieve(query, workspace, limit=retrieval_limit)
            sections = []
            for document in documents:
                label = _source_label(document.metadata or {})
                used_source_labels.add(label)
                sections.append(f"[{label}]\n{document.page_content}")
            result = "\n\n---\n\n".join(sections) if sections else "No matching passages were found in the selected workspace."
            log_event("search_knowledge_base", {"query": query[:MAX_TOOL_ARGUMENTS], "workspace": workspace}, "ok", f"{len(documents)} passages")
            return result
        except Exception as exc:
            log_event("search_knowledge_base", {"query": query[:MAX_TOOL_ARGUMENTS], "workspace": workspace}, "error", str(exc))
            return "Search failed. The local vector database or embedding model may be unavailable."

    @tool
    def list_indexed_sources() -> str:
        """List files indexed in the active workspace. This is read-only."""
        try:
            sources = list_sources(workspace)
            result = "\n".join(f"{item['name']} ({item['chunks']} chunks)" for item in sources)
            log_event("list_indexed_sources", {"workspace": workspace}, "ok", f"{len(sources)} files")
            return result or "No files are indexed in the selected workspace."
        except Exception as exc:
            log_event("list_indexed_sources", {"workspace": workspace}, "error", str(exc))
            return "Could not list indexed sources."

    @tool
    def calculator(expression: str) -> str:
        """Calculate a basic arithmetic expression. Supports numbers and +, -, *, /, //, %, and **."""
        try:
            value = _calculate(expression)
            log_event("calculator", {"expression": expression[:MAX_TOOL_ARGUMENTS]}, "ok", str(value))
            return str(value)
        except (ValueError, TypeError, SyntaxError, ZeroDivisionError, OverflowError) as exc:
            log_event("calculator", {"expression": expression[:MAX_TOOL_ARGUMENTS]}, "rejected", str(exc))
            return f"Calculation rejected: {exc}"

    return [search_knowledge_base, list_indexed_sources, calculator]


def _calculate(expression: str):
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 120:
        raise ValueError("expression must contain 1 to 120 characters")
    tree = ast.parse(expression, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 32:
        raise ValueError("expression is too complex")

    binary_ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    unary_ops = {ast.UAdd: operator.pos, ast.USub: operator.neg}

    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            if isinstance(node.value, float) and not math.isfinite(node.value):
                raise ValueError("numbers must be finite")
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in binary_ops:
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 12:
                raise ValueError("exponents must be between -12 and 12")
            result = binary_ops[type(node.op)](left, right)
            if isinstance(result, int) and result.bit_length() > 1024:
                raise ValueError("result is too large")
            if isinstance(result, float) and not math.isfinite(result):
                raise ValueError("result is not finite")
            return result
        if isinstance(node, ast.UnaryOp) and type(node.op) in unary_ops:
            return unary_ops[type(node.op)](evaluate(node.operand))
        raise ValueError("only numeric constants and basic arithmetic operators are allowed")

    return evaluate(tree)
