"""How the host's replies reach the owner, told to whichever model answers.

The host's replies are spoken aloud and shown in the window as plain text, so
Markdown marks would be read out or shown as they are. The rule is fixed here
and not left to the persona, which the owner may rewrite. Residents get the
same rule in their own prompt (`vision.residents.prompt`).
"""

from __future__ import annotations

REPLY_FORM = (
    "How your replies reach the owner: they are spoken aloud and shown as plain text. Write plain "
    "sentences, and for a list start each line with a hyphen. Never use Markdown marks such as "
    "asterisks, backticks or headings; write a path or a name as it is."
)
PLAIN = "Reply in plain text, without Markdown marks such as asterisks or backticks."
"""The same rule in one short line, for a small local model."""


def with_reply_form(core: str) -> str:
    """The memory core with the rule after it."""
    return f"{core}\n\n{REPLY_FORM}" if core else REPLY_FORM
