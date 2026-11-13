"""Vision: a personal always-on assistant daemon."""

import re

__version__ = "0.1.0b1"
"""The one place the version is written, in PEP 440 spelling (a beta is `b1`).

`pyproject.toml` reads it from here (hatch's dynamic version). Everything people see
is derived from it by `display_version`: `0.1.0b1` shows as `0.1.0-beta`.
"""

_PRE_RELEASE = re.compile(r"^(?P<release>\d+(?:\.\d+)*)(?:(?P<kind>a|b|rc)(?P<number>\d+))?$")
_KINDS = {"a": "alpha", "b": "beta", "rc": "rc"}


def display_version(version: str = __version__) -> str:
    """The version as people read it: `0.1.0b1` is `0.1.0-beta`, `0.1.0b2` is `0.1.0-beta.2`.

    The first pre-release carries no number, so the label stays plain. A final release
    (`0.1.0`) is shown as it is, and anything this does not recognise is left alone.
    """
    match = _PRE_RELEASE.match(version)
    if match is None or match["kind"] is None:
        return version
    label = f"{match['release']}-{_KINDS[match['kind']]}"
    return label if int(match["number"]) == 1 else f"{label}.{int(match['number'])}"
