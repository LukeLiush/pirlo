import argparse
import json
import os
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any, get_args, get_origin

from pirlo.core.models.parameters import Parameter


class ValueConverter:
    _TRUTHY = frozenset({"true", "1", "yes", "on"})

    def convert(self, val: Any, type_func: Callable) -> Any:
        if val is None:
            return None

        origin = get_origin(type_func) or type_func
        if origin is list:
            return self._convert_list(val, type_func)
        if origin is dict:
            return self._convert_dict(val)
        if type_func is bool:
            return self._convert_bool(val)
        if type_func is Path:
            return self._convert_path(val)
        return self._convert_scalar(val, type_func)

    # --- list -------------------------------------------------------------

    def _convert_list(self, val: Any, type_func: Callable) -> list:
        args = get_args(type_func)
        item_type: Callable = args[0] if args else str

        if isinstance(val, list):
            return [self.convert(item, item_type) for item in val]
        if isinstance(val, str):
            return self._list_from_string(val, item_type)
        # Single scalar -> single-element list
        return [self.convert(val, item_type)]

    def _list_from_string(self, val: str, item_type: Callable) -> list:
        stripped = val.strip()
        if stripped.startswith("["):
            try:
                parsed = json.loads(val)
            except json.JSONDecodeError as e:
                sys.stderr.write(
                    f"Warning: Failed to decode list parameter as JSON: {e}\n"
                )
            else:
                if isinstance(parsed, list):
                    return [self.convert(item, item_type) for item in parsed]
        # Fall back to comma-separated split
        return [self.convert(item.strip(), item_type) for item in val.split(",")]

    # --- dict -------------------------------------------------------------

    @staticmethod
    def _convert_dict(val: Any) -> dict:
        if isinstance(val, dict):
            return val
        if isinstance(val, str):
            if not val.strip():
                return {}
            try:
                parsed = json.loads(val)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"Invalid dict parameter (expected JSON object): {e}"
                ) from e
            if not isinstance(parsed, dict):
                raise ValueError(f"Dict parameter did not decode to an object: {val!r}")
            return parsed
        return dict(val) if val else {}

    # --- scalars ----------------------------------------------------------

    def _convert_bool(self, val: Any) -> bool:
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.strip().lower() in self._TRUTHY
        return bool(val)

    @staticmethod
    def _convert_path(val: Any) -> Path:
        return Path(val).expanduser()

    @staticmethod
    def _convert_scalar(val: Any, type_func: Callable) -> Any:
        try:
            return type_func(val)
        except (ValueError, TypeError) as e:
            type_name = getattr(type_func, "__name__", type_func)
            raise ValueError(f"Could not convert {val!r} to {type_name}: {e}") from e


class ParameterSource(ABC):
    """A single precedence layer that supplies raw parameter values.

    Each source returns a ``{param.name: converted_value}`` dict containing
    only the parameters it actually provides, so higher-precedence sources
    can override lower ones via simple dict merging. Parameters a source
    does not provide are omitted (not set to ``None``).
    """

    def __init__(self, converter: ValueConverter) -> None:
        self._converter = converter

    def bind(self, parameters: list[Parameter]) -> dict[str, Any]:
        bound: dict[str, Any] = {}
        for param in parameters:
            raw = self._raw_value(param)
            if raw is not _MISSING:
                bound[param.name] = self._converter.convert(raw, param.type_func)
        return bound

    @abstractmethod
    def _raw_value(self, param: Parameter) -> Any:
        """Return the raw value for ``param`` or ``_MISSING`` if absent."""


class _Missing:
    """Sentinel distinguishing 'not provided' from a provided ``None``."""

    def __repr__(self) -> str:  # pragma: no cover
        return "<MISSING>"


_MISSING = _Missing()


class ArgumentSource(ParameterSource):
    """Values from parsed CLI arguments (the highest precedence)."""

    def __init__(
        self, parsed_args: argparse.Namespace, converter: ValueConverter
    ) -> None:
        super().__init__(converter)
        self._args = parsed_args

    def _raw_value(self, param: Parameter) -> Any:
        # argparse always sets the attribute, defaulting to None when unset,
        # so 'provided' means present AND non-None.
        value = getattr(self._args, param.name, None)
        return value if value is not None else _MISSING


class EnvironmentSource(ParameterSource):
    """Values from environment variables."""

    def _raw_value(self, param: Parameter) -> Any:
        env_names = getattr(param, "env_name", None)
        if not env_names:
            return _MISSING
        if isinstance(env_names, str):
            env_names = [env_names]
        for env_name in env_names:
            if env_name in os.environ:
                return os.environ[env_name]
        return _MISSING


class TomlSource(ParameterSource):
    """Values from the pirlo.toml config section."""

    def __init__(self, toml_config: dict[str, Any], converter: ValueConverter) -> None:
        super().__init__(converter)
        self._toml_config = toml_config

    def _raw_value(self, param: Parameter) -> Any:
        if param.name in self._toml_config:
            return self._toml_config[param.name]
        return _MISSING


class OverrideSource(ParameterSource):
    """Values from explicit dictionary overrides."""

    def __init__(self, overrides: dict[str, Any], converter: ValueConverter) -> None:
        super().__init__(converter)
        self._overrides = overrides

    def _raw_value(self, param: Parameter) -> Any:
        if param.name in self._overrides and self._overrides[param.name] is not None:
            return self._overrides[param.name]
        return _MISSING

