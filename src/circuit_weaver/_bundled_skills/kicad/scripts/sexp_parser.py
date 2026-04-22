"""
S-expression parser for KiCad files.

Parses KiCad's Lisp-like S-expression format into nested Python lists.
Handles quoted strings, multi-line expressions, and large files efficiently.

Usage:
    from sexp_parser import parse_file, find_all, find_first, get_property
"""

import sys
from typing import Any


def parse(text: str) -> list:
    """Parse S-expression text into nested Python lists."""
    tokens = _tokenize(text)
    result = _parse_tokens(tokens, 0)[0]
    return result


def parse_file(path: str) -> list:
    """Parse a KiCad S-expression file."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return parse(f.read())


def _tokenize(text: str) -> list[str]:
    """Tokenize S-expression text into a flat list of tokens."""
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\n\r":
            i += 1
        elif c == "(":
            tokens.append("(")
            i += 1
        elif c == ")":
            tokens.append(")")
            i += 1
        elif c == '"':
            # Quoted string
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                elif text[j] == '"':
                    break
                else:
                    j += 1
            tokens.append(text[i + 1 : j].replace('\\"', '"').replace("\\\\", "\\"))
            i = j + 1
        else:
            # Unquoted atom
            j = i
            while j < n and text[j] not in " \t\n\r()\"":
                j += 1
            tokens.append(text[i:j])
            i = j
    return tokens


def _parse_tokens(tokens: list[str], pos: int) -> tuple[Any, int]:
    """Recursively parse tokens starting at pos. Returns (result, new_pos)."""
    if tokens[pos] == "(":
        lst = []
        pos += 1
        while pos < len(tokens) and tokens[pos] != ")":
            item, pos = _parse_tokens(tokens, pos)
            lst.append(item)
        return lst, pos + 1  # skip ')'
    else:
        return tokens[pos], pos + 1


def find_all(node: list, keyword: str) -> list[list]:
    """Find all direct children of node that start with keyword.

    Example: find_all(root, "symbol") returns all (symbol ...) blocks.
    """
    if not isinstance(node, list):
        return []
    return [child for child in node if isinstance(child, list) and len(child) > 0 and child[0] == keyword]


def find_first(node: list, keyword: str) -> list | None:
    """Find first direct child of node that starts with keyword."""
    if not isinstance(node, list):
        return None
    for child in node:
        if isinstance(child, list) and len(child) > 0 and child[0] == keyword:
            return child
    return None


def find_deep(node: list, keyword: str) -> list[list]:
    """Recursively find all nodes starting with keyword at any depth."""
    results = []
    if not isinstance(node, list):
        return results
    _find_deep_acc(node, keyword, results)
    return results


def _find_deep_acc(node: list, keyword: str, acc: list) -> None:
    """Accumulator helper for find_deep — avoids intermediate list allocations."""
    if len(node) > 0 and node[0] == keyword:
        acc.append(node)
    for child in node:
        if isinstance(child, list):
            _find_deep_acc(child, keyword, acc)


def get_value(node: list, keyword: str) -> str | None:
    """Get the value of a simple (keyword value) pair.

    Example: get_value(symbol, "lib_id") -> "Device:C"
    """
    child = find_first(node, keyword)
    if child and len(child) > 1:
        return str(child[1])
    return None


def get_property(node: list, prop_name: str) -> str | None:
    """Get the value of a named property.

    Example: get_property(symbol, "Reference") -> "C7"
    """
    for child in node:
        if isinstance(child, list) and len(child) >= 3 and child[0] == "property" and child[1] == prop_name:
            return str(child[2])
    return None


def get_at(node: list) -> tuple[float, float, float] | None:
    """Get (x, y, angle) from an (at x y [angle]) node."""
    at = find_first(node, "at")
    if at and len(at) >= 3:
        x = float(at[1])
        y = float(at[2])
        angle = float(at[3]) if len(at) > 3 else 0.0
        return (x, y, angle)
    return None


def get_xy(node: list) -> tuple[float, float] | None:
    """Get (x, y) from an (xy x y) node."""
    if isinstance(node, list) and len(node) >= 3 and node[0] == "xy":
        return (float(node[1]), float(node[2]))
    return None


def has_flag(node: list, flag: str) -> bool:
    """Check if a node contains a flag like 'hide' or 'yes'."""
    return flag in node


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python sexp_parser.py <file.kicad_sch|.kicad_pcb>")
        sys.exit(1)
    tree = parse_file(sys.argv[1])
    print(f"Parsed {sys.argv[1]}: root node = {tree[0] if isinstance(tree, list) else tree}")
    print(f"Top-level children: {len(tree) - 1}")
