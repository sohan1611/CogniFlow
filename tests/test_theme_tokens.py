"""The two dark palettes must stay identical.

Dark is reachable two ways -- an OS-level preference, matched by
`@media (prefers-color-scheme: dark)`, and an explicit choice in the theme switcher,
matched by `:root[data-theme="dark"]`. CSS gives no way to define a set of custom
properties once and attach it to both, because one of them lives inside a media query,
so the palette is written out twice.

That duplication has already produced the bug it invites. A palette change landed in the
media block only, and the attribute block kept the previous colours -- so a student who
picked "Dark" in the switcher got one theme, and a student whose laptop was already in
dark mode got a different one. Nothing in the build notices: both blocks are valid CSS,
both render, and the wrong one is only visible if you happen to test the path you did not
change.

This is the only thing that can notice. It parses the stylesheet and compares the two
token sets directly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CSS = Path(__file__).resolve().parents[1] / "web" / "app" / "globals.css"


def _block(css: str, start: str) -> str:
    """The text of the brace-balanced rule beginning at `start`."""
    i = css.index(start)
    depth, j = 0, i
    while True:
        if css[j] == "{":
            depth += 1
        elif css[j] == "}":
            depth -= 1
            if depth == 0:
                return css[i:j]
        j += 1


def _tokens(block: str) -> dict[str, str]:
    """Custom properties in a block, with whitespace normalised.

    Normalising matters: `rgba(255,255,255,.07)` and `rgba(255, 255, 255, .07)` are the
    same colour, and a test that called those a mismatch would cry wolf on formatting.
    """
    return {
        m.group(1): re.sub(r"\s+", " ", m.group(2)).strip()
        for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", block)
    }


@pytest.fixture(scope="module")
def palettes() -> tuple[dict[str, str], dict[str, str]]:
    css = CSS.read_text(encoding="utf-8")
    return (
        _tokens(_block(css, "@media (prefers-color-scheme: dark)")),
        _tokens(_block(css, ':root[data-theme="dark"]')),
    )


def test_neither_dark_block_defines_a_token_the_other_lacks(palettes) -> None:
    """A token in one block only is a colour that changes depending on how you got here."""
    media, explicit = palettes
    assert media, "no tokens found in the prefers-color-scheme block -- has it moved?"

    only_media = sorted(set(media) - set(explicit))
    only_explicit = sorted(set(explicit) - set(media))
    assert not only_media, (
        "defined for a dark OS but not for an explicit dark choice: " f"{only_media}"
    )
    assert not only_explicit, (
        "defined for an explicit dark choice but not for a dark OS: " f"{only_explicit}"
    )


def test_the_two_dark_blocks_agree_on_every_value(palettes) -> None:
    """Same token, same colour, whichever route the student took to dark mode."""
    media, explicit = palettes
    differing = {
        key: (media[key], explicit[key])
        for key in set(media) & set(explicit)
        if media[key] != explicit[key]
    }
    assert not differing, (
        "the two dark palettes disagree, so picking Dark and having a dark OS give "
        f"different themes:\n"
        + "\n".join(f"  {k}\n    media: {v[0]}\n    attr : {v[1]}" for k, v in sorted(differing.items())[:10])
    )


def test_the_light_palette_is_defined_on_bare_root(palettes) -> None:
    """Every colour needs a definition outside a media or attribute block.

    A token whose ONLY definition lives in a dark block is undefined in light mode, which
    renders as an inherited or transparent colour rather than an error.
    """
    css = CSS.read_text(encoding="utf-8")
    light = _tokens(_block(css, ":root {"))
    media, _ = palettes

    missing = sorted(set(media) - set(light))
    assert not missing, f"dark-only tokens with no light definition: {missing}"
