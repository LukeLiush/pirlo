import argparse
import json
import os
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any, get_args, get_origin

from pirlo.core.models.parameters import LinkParameter


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
        if isinstance(type_func, type) and not issubclass(type_func, (str, int, float, Path, bool)):
            return str(val) if val is not None else None
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
                parsed = val
            if isinstance(parsed, list):
                return [self.convert(item, item_type) for item in parsed]

        items = [s.strip() for s in val.split(",") if s.strip()]
        return [self.convert(item, item_type) for item in items]

    # --- dict -------------------------------------------------------------

    @staticmethod
    def _convert_dict(val: Any) -> dict:
        if isinstance(val, dict):
            return val
        if isinstance(val, str):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError as e:
                sys.stderr.write(
                    f"Warning: Failed to decode dict parameter as JSON: {e}\n"
                )
        return {}

    # --- bool -------------------------------------------------------------

    def _convert_bool(self, val: Any) -> bool:
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.strip().lower() in self._TRUTHY
        return bool(val)

    # --- path -------------------------------------------------------------

    @staticmethod
    def _convert_path(val: Any) -> Path:
        if isinstance(val, Path):
            return val
        return Path(str(val))

    # --- scalar -----------------------------------------------------------

    @staticmethod
    def _convert_scalar(val: Any, type_func: Callable) -> Any:
        try:
            return type_func(val)
        except (ValueError, TypeError) as e:
            type_name = getattr(type_func, "__name__", str(type_func))
            raise ValueError(f"Could not convert {val!r} to {type_name}: {e}") from e


class ParameterSource(ABC):
    """A single precedence layer that supplies raw parameter values."""

    def __init__(self, converter: ValueConverter) -> None:
        self._converter = converter

    def bind(self, parameters: list[Any]) -> dict[str, Any]:
        bound: dict[str, Any] = {}
        for param in parameters:
            name = (
                param["name"] if isinstance(param, dict) else getattr(param, "name", "")
            )
            type_func = (
                param["type"]
                if isinstance(param, dict)
                else getattr(param, "type_func", str)
            )
            is_link = (
                param.get("is_link", False)
                if isinstance(param, dict)
                else isinstance(param, LinkParameter)
            )
            raw = self._raw_value(param)
            if raw is not _MISSING:
                if is_link:
                    bound[name] = str(raw) if raw is not None else None
                else:
                    bound[name] = self._converter.convert(raw, type_func)
        return bound

    @abstractmethod
    def _raw_value(self, param: Any) -> Any:
        """Return the raw value for ``param`` or ``_MISSING`` if absent."""


class _Missing:
    """Sentinel distinguishing 'not provided' from a provided ``None``."""

    def __repr__(self) -> str:  # pragma: no cover
        return "<MISSING>"


_MISSING = _Missing()


class ArgumentSource(ParameterSource):
    """Binds parameters from a parsed ``argparse.Namespace``."""

    def __init__(
        self, parsed_args: argparse.Namespace, converter: ValueConverter
    ) -> None:
        super().__init__(converter)
        self._args = parsed_args

    def _raw_value(self, param: Any) -> Any:
        name = param["name"] if isinstance(param, dict) else getattr(param, "name", "")
        if hasattr(self._args, name):
            return getattr(self._args, name)
        return _MISSING


class EnvironmentSource(ParameterSource):
    """Binds parameters from environment variables."""

    def _raw_value(self, param: Any) -> Any:
        env_names: list[str] = []
        if isinstance(param, dict):
            raw_env = param.get("env_name")
            if isinstance(raw_env, str):
                env_names = [raw_env]
            elif isinstance(raw_env, list):
                env_names = raw_env
        else:
            env_names = param.env_names

        for env_name in env_names:
            if env_name in os.environ:
                return os.environ[env_name]
        return _MISSING


class TomlSource(ParameterSource):
    """Binds parameters from a parsed TOML config table."""

    def __init__(self, toml_data: dict[str, Any], converter: ValueConverter) -> None:
        super().__init__(converter)
        self._data = toml_data

    def _raw_value(self, param: Any) -> Any:
        name = param["name"] if isinstance(param, dict) else getattr(param, "name", "")
        if name in self._data:
            return self._data[name]
        return _MISSING


class OverrideSource(ParameterSource):
    """Binds parameters from an explicit keyword override dict."""

    def __init__(
        self, overrides: dict[str, Any], converter: ValueConverter
    ) -> None:
        super().__init__(converter)
        self._overrides = overrides

    def _raw_value(self, param: Any) -> Any:
        name = param["name"] if isinstance(param, dict) else getattr(param, "name", "")
        if name in self._overrides and self._overrides[name] is not None:
            return self._overrides[name]
        return _MISSING
