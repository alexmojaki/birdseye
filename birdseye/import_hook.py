import logging
import sys
from importlib.util import spec_from_loader
import ast


# This is based on the MacroPy import hook
# https://github.com/lihaoyi/macropy/blob/46ee500b877d5a32b17391bb8122c09b15a1826a/macropy/core/import_hooks.py

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


class BirdsEyeFinder(object):
    """Loads a module and looks for tracing inside, only providing a loader
    if it finds some.
    """

    def _find_plain_spec(self, fullname, path, target):
        """Try to find the original module using all the
        remaining meta_path finders."""
        spec = None
        for finder in sys.meta_path:
            # when testing with pytest, it installs a finder that for
            # some yet unknown reasons makes birdseye
            # fail. For now it will just avoid using it and pass to
            # the next one
            if finder is self or 'pytest' in finder.__module__:
                continue
            if hasattr(finder, 'find_spec'):
                spec = finder.find_spec(fullname, path, target=target)
            elif hasattr(finder, 'load_module'):
                spec = spec_from_loader(fullname, finder)

            if spec is not None and spec.origin != 'builtin':
                return spec

    def find_spec(self, fullname, path, target=None):
        spec = self._find_plain_spec(fullname, path, target)
        if spec is None or not (hasattr(spec.loader, 'get_source') and
                                callable(spec.loader.get_source)):  # noqa: E128
            if fullname != 'org':
                # stdlib pickle.py at line 94 contains a ``from
                # org.python.core for Jython which is always failing,
                # of course
                logging.debug('Failed finding spec for %s', fullname)
            return

        try:
            source = spec.loader.get_source(fullname)
        except ImportError:
            logging.debug('Loader for %s was unable to find the sources',
                          fullname)
            return
        except Exception:
            logging.exception('Loader for %s raised an error', fullname)
            return

        if not source or 'birdseye' not in source:
            return

        deep, trace_stmt = should_trace(source)

        if not trace_stmt:
            return

        loader = BirdsEyeLoader(spec, source, deep)
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
