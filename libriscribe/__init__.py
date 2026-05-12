"""Compatibility package shim for running Libriscribe from the repository root.

The actual application package lives in ``libriscribe/src/libriscribe``. When
commands are executed from the workspace root (``d:/weidong``), Python may find
this repository directory first and otherwise fail to resolve submodules such as
``libriscribe.knowledge_base``. Extending ``__path__`` keeps root-level launches
and installed/editable launches consistent.
"""

from pathlib import Path
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)  # type: ignore[name-defined]

_src_pkg = Path(__file__).resolve().parent / "src" / "libriscribe"
if _src_pkg.exists():
    src_pkg_text = str(_src_pkg)
    if src_pkg_text not in __path__:
        __path__.append(src_pkg_text)

__all__: list[str] = []
