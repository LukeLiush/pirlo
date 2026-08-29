import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pirlo.core.decorators import playbook

PLAYBOOK_DECORATOR_NAME: str = playbook.__name__
type DecoratorValue = str | int | float | bool


@dataclass(frozen=True)
class PlaybookSpec:
    """Immutable data record representing a discovered playbook specification."""

    name: str
    description: str
    module_path: str
    class_name: str
    file_path: Path
    extra_kwargs: dict[str, DecoratorValue] = field(default_factory=dict)


class PlaybookScanner:
    """Fast AST scanner that recursively discovers @playbook definitions without importing code."""

    @classmethod
    def scan_directory(cls, directory: Path) -> dict[str, PlaybookSpec]:
        """Recursively traverses directory for .py files containing @playbook decorators."""
        specs: dict[str, PlaybookSpec] = {}
        if not directory.exists():
            return specs

        py_file: Path
        for py_file in directory.glob("**/*.py"):
            if cls._should_skip_file(py_file):
                continue
            spec: PlaybookSpec | None = cls.scan_file(py_file, root_dir=directory)
            if spec:
                specs[spec.name] = spec
        return specs

    @classmethod
    def scan_file(cls, file_path: Path, root_dir: Path) -> PlaybookSpec | None:
        """Main orchestrator for scanning a single python file AST."""
        tree: ast.AST | None = cls._parse_ast_tree(file_path)
        if not tree:
            return None

        match: tuple[ast.ClassDef, ast.Call] | None = (
            cls._find_playbook_decorator_match(tree)
        )
        if not match:
            return None

        class_node: ast.ClassDef
        decorator_call: ast.Call
        class_node, decorator_call = match

        kwargs: dict[str, DecoratorValue] = cls._extract_decorator_kwargs(
            decorator_call
        )

        # Strict validation: 'name' keyword argument is required in @playbook(name="...")
        name_val: DecoratorValue | None = kwargs.pop("name", None)
        if not isinstance(name_val, str) or not name_val:
            sys.stderr.write(
                f"Warning: Playbook class '{class_node.name}' in {file_path} "
                "has a @playbook decorator missing the required 'name' argument.\n"
            )
            return None

        name: str = name_val
        desc_val: DecoratorValue | None = kwargs.pop("description", "")
        description: str = str(desc_val) if isinstance(desc_val, str) else ""

        module_path: str = cls._resolve_module_path(file_path, root_dir)

        return PlaybookSpec(
            name=name,
            description=description,
            module_path=module_path,
            class_name=class_node.name,
            file_path=file_path,
            extra_kwargs=kwargs,
        )

    # --- Small Single-Responsibility Helper Methods ---

    @classmethod
    def _should_skip_file(cls, file_path: Path) -> bool:
        """Filter out internal files (__init__.py, _private.py) and test directories."""
        if file_path.name.startswith("_"):
            return True
        return "tests" in file_path.parts or "test_" in file_path.name

    @classmethod
    def _parse_ast_tree(cls, file_path: Path) -> ast.AST | None:
        """Safely reads file and parses AST tree."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return ast.parse(f.read(), filename=str(file_path))
        except Exception:  # noqa: BLE001
            return None

    @classmethod
    def _find_playbook_decorator_match(
        cls, tree: ast.AST
    ) -> tuple[ast.ClassDef, ast.Call] | None:
        """Traverses AST nodes to locate a ClassDef with a @playbook(...) decorator."""
        ast_node: ast.AST
        for ast_node in ast.walk(tree):
            if isinstance(ast_node, ast.ClassDef):
                class_node: ast.ClassDef = ast_node
                decorator_node: ast.AST
                for decorator_node in class_node.decorator_list:
                    if cls._is_playbook_decorator(decorator_node):
                        assert isinstance(decorator_node, ast.Call)
                        return class_node, decorator_node
        return None

    @classmethod
    def _is_playbook_decorator(cls, decorator_node: ast.AST) -> bool:
        """Checks if an AST decorator node matches @playbook(...) or @module.playbook(...)."""
        if not isinstance(decorator_node, ast.Call):
            return False
        # Case 1: @playbook(...) -> func is ast.Name(id="playbook")
        if (
            isinstance(decorator_node.func, ast.Name)
            and decorator_node.func.id == PLAYBOOK_DECORATOR_NAME
        ):
            return True
        # Case 2: @decorators.playbook(...) -> func is ast.Attribute(attr="playbook")
        return (
            isinstance(decorator_node.func, ast.Attribute)
            and decorator_node.func.attr == PLAYBOOK_DECORATOR_NAME
        )

    @classmethod
    def _extract_decorator_kwargs(
        cls, decorator_call: ast.Call
    ) -> dict[str, DecoratorValue]:
        """Generic future-proof extraction of keyword arguments from @playbook(...) call."""
        kwargs: dict[str, DecoratorValue] = {}

        kw: ast.keyword
        for kw in decorator_call.keywords:
            if kw.arg and isinstance(kw.value, ast.Constant):
                val: Any = kw.value.value
                if isinstance(val, (str, int, float, bool)):
                    kwargs[kw.arg] = val

        return kwargs

    @classmethod
    def _resolve_module_path(cls, file_path: Path, root_dir: Path) -> str:
        """Resolves Python module dot-notation path (e.g. pirlo.playbooks.autopass.main)."""
        if "src" in file_path.parts:
            idx: int = file_path.parts.index("src")
            rel_parts: tuple[str, ...] = file_path.parts[idx + 1 :]
            module_parts: list[str] = list(Path(*rel_parts).with_suffix("").parts)
            return ".".join(module_parts)

        rel_path: Path = file_path.relative_to(root_dir.parent)
        module_parts_fallback: list[str] = list(rel_path.with_suffix("").parts)
        return ".".join(module_parts_fallback)
