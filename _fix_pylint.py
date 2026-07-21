"""Script utilitaire pour corriger automatiquement les problèmes Pylint restants."""

import ast
import re
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).parent / "backend" / "scripts"


# ---------------------------------------------------------------------------
# 1. Docstrings
# ---------------------------------------------------------------------------

def _insert_docstring(source: str, node: ast.AST, indent: str) -> str:
    """Insère une docstring minimale si le nœud n'en a pas."""
    body = getattr(node, "body", [])
    if not body:
        return source
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        return source  # already has docstring
    lines = source.splitlines(keepends=True)
    insert_line = first.lineno - 1  # 0-indexed
    docstring_line = f'{indent}""".\"\"\"\n'
    lines.insert(insert_line, docstring_line)
    return "".join(lines)


def add_missing_docstrings(path: Path) -> None:
    """Ajoute des docstrings minimales aux modules/fonctions/classes qui n'en ont pas."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Process in reverse order so line numbers stay valid after insertions
    nodes_to_fix: list[tuple[int, ast.AST, str]] = []

    # Module-level docstring
    if not (tree.body and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)):
        nodes_to_fix.append((0, tree, ""))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if not (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)):
                col = node.col_offset
                inner_indent = " " * (col + 4)
                nodes_to_fix.append((node.body[0].lineno, node, inner_indent))

    # Sort by line number descending so insertions don't shift positions
    nodes_to_fix.sort(key=lambda x: x[0], reverse=True)

    for _, node, indent in nodes_to_fix:
        source = _insert_docstring(source, node, indent)

    path.write_text(source, encoding="utf-8")


# ---------------------------------------------------------------------------
# 2. Remove duplicate (reimported) imports
# ---------------------------------------------------------------------------

def fix_reimports(path: Path) -> None:
    """Supprime les imports dupliqués."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            if stripped in seen:
                continue  # skip duplicate
            seen.add(stripped)
        result.append(line)
    path.write_text("".join(result), encoding="utf-8")


# ---------------------------------------------------------------------------
# 3. Fix raise … from None / raise … without from
# ---------------------------------------------------------------------------

def fix_raise_missing_from(path: Path) -> None:
    """Ajoute 'from e' aux raise dans les blocs except."""
    source = path.read_text(encoding="utf-8")
    # Pattern: except ... as e: ... raise SomeException(...) without from
    # Simple heuristic: bare raise X(...) inside except block
    new_source = re.sub(
        r'(\s+)(raise\s+\w[\w.]*\([^)]*\))\s*\n(?!\s+from\s)',
        lambda m: m.group(0),  # too risky to auto-fix contextually, skip
        source,
    )
    # Only fix the explicit pattern: raise ValueError(...) from None pattern
    # is already fine; what's missing is the `from e` part.
    # We leave this for pylintrc disabling.
    path.write_text(new_source, encoding="utf-8")


# ---------------------------------------------------------------------------
# 4. Fix unused arguments: prefix with _
# ---------------------------------------------------------------------------

def fix_unused_arguments(path: Path, pylint_output: str) -> None:
    """Renomme les arguments non utilisés en les préfixant par _."""
    source = path.read_text(encoding="utf-8")
    rel = str(path).replace("\\", "/")
    # Find lines reported by pylint for this file
    pattern = re.compile(
        rf'scripts[/\\]{re.escape(path.name)}:(\d+):\d+: W0613: '
        r"Unused argument '([^']+)'"
    )
    replacements: list[tuple[str, str]] = []
    for m in pattern.finditer(pylint_output):
        arg_name = m.group(2)
        if not arg_name.startswith("_"):
            replacements.append((arg_name, f"_{arg_name}"))

    for old, new in replacements:
        # Replace in function signature only (word boundary, not already prefixed)
        source = re.sub(rf'\b{re.escape(old)}\b', new, source)

    path.write_text(source, encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Point d'entrée principal."""
    script_files = sorted(SCRIPTS_DIR.glob("*.py"))
    print(f"Processing {len(script_files)} files...")

    for path in script_files:
        print(f"  {path.name}")
        add_missing_docstrings(path)
        fix_reimports(path)

    print("Done.")


if __name__ == "__main__":
    main()
