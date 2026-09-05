"""Regenerate both recording PDFs in docs/.

    pip install reportlab
    python scripts/docs_pdf/build.py

These live in the repository rather than in a scratch directory because the PDFs are
committed: a generated artefact whose generator has been lost is an artefact nobody can
correct. Both are checked for layout faults before they are written -- see
`Doc.check_layout` -- because there is no PDF renderer on the build machine and text
extraction cannot see a table printing over its neighbour.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import guide_doc  # noqa: E402
import script_doc  # noqa: E402

if __name__ == "__main__":
    print("guide:")
    guide_doc.build(str(ROOT / "docs/CogniFlow_Video_Guide.pdf"))
    print("script:")
    script_doc.build(str(ROOT / "docs/CogniFlow_Video_Script.pdf"))
