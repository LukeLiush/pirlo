import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PLAYBOOK_DECORATOR_NAMES: set[str] = {"playbook", "play"}
type DecoratorValue = str | int | float | bool


@dataclass(frozen=True)
class PlaySpec:
    """Immutable data record representing a discovered play specification."""

    name: str
    description: str
    module_path: str
    class_name: str
    file_path: Path
    extra_kwargs: dict[str, DecoratorValue] = field(default_factory=dict)


class PlayScanner:
    """Fast AST scanner that recursively discovers @play definitions without importing code."""

    @classmethod
    def scan_directory(cls, directory: Path) -> dict[str, PlaySpec]:
        """Recursively traverses directory for .py files containing @play decorators."""
        specs: dict[str, PlaySpec] = {}
        if not directory.exists():
            return specs

        py_file: Path
        for py_file in directory.glob("**/*.py"):
            if cls._should_skip_file(py_file):
                continue
            file_specs: list[PlaySpec] = cls.scan_file_specs(
                py_file, root_dir=directory
            )
            for spec in file_specs:
                specs[spec.name] = spec
        return specs

    @classmethod
    def get_play_class(cls, play_name: str) -> type[object]:
        """Dynamically imports and returns the Python class for a given play_name."""
        import importlib

        from pirlo.core.config import get_workspace_path

        workspace_path = get_workspace_path()
        playbooks_dir = workspace_path / "src" / "pirlo" / "playbooks"
        specs = cls.scan_directory(playbooks_dir)
        spec = specs.get(play_name)
        if not spec:
            raise KeyError(f"Play '{play_name}' not found.")

        module = importlib.import_module(spec.module_path)
        return getattr(module, spec.class_name)  # type: ignore[no-any-return]

    get_playbook_class = get_play_class

    @classmethod
    def scan_file(cls, file_path: Path, root_dir: Path) -> PlaySpec | None:
        """Backward-compatible helper returning the first play spec in a single python file."""
        specs: list[PlaySpec] = cls.scan_file_specs(file_path, root_dir=root_dir)
        return specs[0] if specs else None

    @classmethod
    def scan_file_specs(cls, file_path: Path, root_dir: Path) -> list[PlaySpec]:
        """Main orchestrator for scanning ALL @play definitions in a single python file AST."""
        tree: ast.AST | None = cls._parse_ast_tree(file_path)
        if not tree:
            return []

        matches: list[tuple[ast.ClassDef, ast.Call]] = (
            cls._find_all_playbook_decorator_matches(tree)
        )
        if not matches:
            return []

        results: list[PlaySpec] = []
        class_node: ast.ClassDef
        decorator_call: ast.Call
        for class_node, decorator_call in matches:
            kwargs: dict[str, DecoratorValue] = cls._extract_decorator_kwargs(
                decorator_call
            )

            # Strict validation: 'name' keyword argument is required in @play(name="...")
            name_val: DecoratorValue | None = kwargs.pop("name", None)
            if not isinstance(name_val, str) or not name_val:
                sys.stderr.write(
                    f"Warning: Play class '{class_node.name}' in {file_path} "
                    "has a @play decorator missing the required 'name' argument.\n"
                )
                continue

            name: str = name_val
            desc_val: DecoratorValue | None = kwargs.pop("description", "")
            description: str = str(desc_val) if isinstance(desc_val, str) else ""

            module_path: str = cls._resolve_module_path(file_path, root_dir)

            results.append(
                PlaySpec(
                    name=name,
                    description=description,
                    module_path=module_path,
                    class_name=class_node.name,
                    file_path=file_path,
                    extra_kwargs=kwargs,
                )
            )

        return results

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
    def _find_all_playbook_decorator_matches(
        cls, tree: ast.AST
    ) -> list[tuple[ast.ClassDef, ast.Call]]:
        """Traverses AST nodes to locate ALL ClassDefs with @play(...) decorators."""
        matches: list[tuple[ast.ClassDef, ast.Call]] = []
        ast_node: ast.AST
        for ast_node in ast.walk(tree):
            if isinstance(ast_node, ast.ClassDef):
                class_node: ast.ClassDef = ast_node
                decorator_node: ast.AST
                for decorator_node in class_node.decorator_list:
                    if cls._is_playbook_decorator(decorator_node):
                        assert isinstance(decorator_node, ast.Call)
                        matches.append((class_node, decorator_node))
        return matches

    @classmethod
    def _is_playbook_decorator(cls, decorator_node: ast.AST) -> bool:
        """Checks if an AST decorator node matches @playbook(...) or @play(...)."""
        if not isinstance(decorator_node, ast.Call):
            return False
        # Case 1: @playbook(...) or @play(...) -> func is ast.Name
        if (
            isinstance(decorator_node.func, ast.Name)
            and decorator_node.func.id in PLAYBOOK_DECORATOR_NAMES
        ):
            return True
        # Case 2: @decorators.playbook(...) or @decorators.play(...) -> func is ast.Attribute
        return (
            isinstance(decorator_node.func, ast.Attribute)
            and decorator_node.func.attr in PLAYBOOK_DECORATOR_NAMES
        )

    @classmethod
    def _extract_decorator_kwargs(
        cls, decorator_call: ast.Call
    ) -> dict[str, DecoratorValue]:
        """Generic future-proof extraction of keyword arguments from @play(...) call."""
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


# Backward-compatibility aliases
PlaybookSpec = PlaySpec
PlaybookScanner = PlayScanner
