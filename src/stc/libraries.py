# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Discover libraries and resolve selective Structured Text imports."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


MANIFEST_NAME = "stc-library.json"


class LibraryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LibraryImport:
    library: str
    symbol: str
    source_name: str
    source: str


@dataclass(slots=True)
class ResolvedLibraries:
    imports: list[LibraryImport] = field(default_factory=list)

class LibraryResolver:
    def __init__(self, search_paths=()):
        self.search_paths = tuple(Path(path) for path in search_paths)

    def resolve(self, imports: tuple[str, ...] | list[str]) -> ResolvedLibraries:
        result = ResolvedLibraries()
        seen: set[tuple[str, str]] = set()
        for request in imports:
            library_name, separator, selected = request.partition(":")
            manifest_path = self._find_manifest(library_name)
            manifest = self._load_manifest(manifest_path)
            exports = manifest.get("exports")
            if not isinstance(exports, dict) or not exports:
                raise LibraryError(f"Library {library_name!r} has no exports")
            names = [selected] if separator else list(exports)
            for name in names:
                if name not in exports:
                    raise LibraryError(f"Library {library_name!r} does not export {name!r}")
                key = (library_name.casefold(), name.casefold())
                if key in seen:
                    continue
                seen.add(key)
                result.imports.append(self._load_export(manifest_path.parent, library_name, name, exports[name]))
        return result

    def _find_manifest(self, library_name: str) -> Path:
        candidates = []
        for root in self.search_paths:
            candidates.extend((root / library_name / MANIFEST_NAME, root / MANIFEST_NAME))
        for candidate in candidates:
            if candidate.is_file():
                manifest = self._load_manifest(candidate)
                if str(manifest.get("name", "")).casefold() == library_name.casefold():
                    return candidate
        paths = ", ".join(str(path) for path in self.search_paths) or "<none>"
        raise LibraryError(f"Library {library_name!r} was not found in: {paths}")

    @staticmethod
    def _load_manifest(path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LibraryError(f"Cannot load library manifest {path}: {exc}") from exc
        if data.get("schema") != 1 or not isinstance(data.get("name"), str):
            raise LibraryError(f"Invalid library manifest {path}")
        return data

    def _load_export(self, root: Path, library: str, symbol: str, spec) -> LibraryImport:
        if isinstance(spec, str):
            spec = {"source": spec}
        if not isinstance(spec, dict) or not isinstance(spec.get("source"), str):
            raise LibraryError(f"Invalid export {library}:{symbol}")
        source_path = root / spec["source"]
        try:
            source = source_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise LibraryError(f"Cannot read library source {source_path}: {exc}") from exc

        return LibraryImport(library, symbol, str(source_path), source)
