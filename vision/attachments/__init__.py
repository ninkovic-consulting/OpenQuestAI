"""Images the owner sends: from the window's chat and widget, and from the paired phone.

`ImageStore` checks, cleans and keeps them (`clean.py` has the rules and the
limits), the session hands them to the brain with the message they came with,
and `build_router` serves them back to the owner's window only.
"""

from __future__ import annotations

from vision.attachments.clean import MAX_PER_MESSAGE, ImageRefused, limits
from vision.attachments.routes import build_router
from vision.attachments.store import ImageStore, NoSuchImage

__all__ = ["MAX_PER_MESSAGE", "ImageRefused", "ImageStore", "NoSuchImage", "build_router", "limits"]
