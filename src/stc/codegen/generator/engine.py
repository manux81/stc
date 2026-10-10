"""Restricted renderer for validated generator rules."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import re
from typing import Any

from .loader import GeneratorBundle, GeneratorError


class GeneratorEngine:
    def __init__(self, bundle: GeneratorBundle):
        self.bundle = bundle

    def map(self, section: str, value: str) -> str:
        rule = self.bundle.rules[section]
        mapping = rule.mapping or {}
        return mapping.get(str(value), mapping.get(str(value).upper(), str(value)))

    def render(self, section: str, values: Any = None, /, **kwargs: Any) -> str:
        rule = self.bundle.rules[section]
        data = asdict(values) if values is not None and is_dataclass(values) else dict(values or {})
        data.update(kwargs)
        for dependency in rule.uses:
            data[dependency] = self.render(dependency, data)
        if rule.when:
            key = rule.when.strip().removeprefix("{").removesuffix("}")
            if not data.get(key):
                return ""
        if rule.mapping is not None and rule.template is None and rule.each is None:
            return self.map(section, str(data.get("value", data.get("name", ""))))
        try:
            if rule.each is not None:
                rendered = [self._substitute(section, rule.each, {**data, **item}) for item in data.get("items", ())]
                return rule.separator.join(rendered)
            return self._substitute(section, rule.template or "", data)
        except KeyError as exc:
            raise GeneratorError(f"section [{section}] was not given value {{{exc.args[0]}}}") from exc

    @staticmethod
    def _substitute(section: str, template: str, data: dict[str, Any]) -> str:
        def replace(match):
            key = match.group(1)
            if key not in data:
                raise KeyError(key)
            return str(data[key])
        return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, template)
