from __future__ import annotations

import sys
from importlib.machinery import ModuleSpec
from importlib.util import spec_from_loader
import ast
from types import ModuleType
from typing import Sequence, Iterator, cast


class BirdsEyeLoader:
    def __init__(self, spec, source, deep):
        self._spec = spec
        self.source = source
        self.deep = deep

    def create_module(self, spec):
        pass

    def exec_module(self, module):
        from birdseye.bird import eye
        eye.exec_string(
            source=self.source,
            filename=self._spec.origin,
            globs=module.__dict__,
            locs=module.__dict__,
            deep=self.deep,
        )

    def get_filename(self, fullname):
        return self._spec.loader.get_filename(fullname)

    def is_package(self, fullname):
        return self._spec.loader.is_package(fullname)


class BirdsEyeFinder:
    """Loads a module and looks for tracing inside, only providing a loader
    if it finds some.
    """

    def _find_plain_specs(
        self, fullname: str, path: Sequence[str] | None, target: ModuleType | None
    ) -> Iterator[ModuleSpec]:
        """Yield module specs returned by other finders on `sys.meta_path`."""
        for finder in sys.meta_path:
            # Skip this finder or any like it to avoid infinite recursion.
            if isinstance(finder, BirdsEyeFinder):
                continue

            try:
                plain_spec = finder.find_spec(fullname, path, target)
            except Exception:  # pragma: no cover
                continue

            if plain_spec:
                yield plain_spec

    def find_spec(
        self, fullname: str, path: Sequence[str] | None, target: ModuleType | None = None
    ) -> ModuleSpec | None:
        """This is the method that is called by the import system.

        It uses the other existing meta path finders to do most of the standard work,
        particularly finding the module's source code.
        If it finds a module spec, it returns a new spec that uses the BirdsEyeLoader.
        """
        for plain_spec in self._find_plain_specs(fullname, path, target):
            # Not all loaders have get_source, but it's an abstract method of the standard ABC InspectLoader.
            # In particular it's implemented by `importlib.machinery.SourceFileLoader`
            # which is provided by default.
            get_source = getattr(plain_spec.loader, 'get_source', None)
            if not callable(get_source):  # pragma: no cover
                continue

            try:
                source = cast(str, get_source(fullname))
            except Exception:  # pragma: no cover
                continue

            if not source:
                continue

            if "birdseye" not in source:
                return None

            deep, trace_stmt = should_trace(source)

            if not trace_stmt:
                return None

            loader = BirdsEyeLoader(plain_spec, source, deep)
            return spec_from_loader(fullname, loader)


def should_trace(source):
    trace_stmt = None
    deep = False
    for stmt in ast.parse(source).body:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                if alias.name.startswith('birdseye.trace_module'):
                    trace_stmt = stmt
                    if alias.name.endswith('deep'):
                        deep = True

        if isinstance(stmt, ast.ImportFrom) and stmt.module == 'birdseye':
            for alias in stmt.names:
                if alias.name.startswith('trace_module'):
                    trace_stmt = stmt
                    if alias.name.endswith('deep'):
                        deep = True
    return deep, trace_stmt
