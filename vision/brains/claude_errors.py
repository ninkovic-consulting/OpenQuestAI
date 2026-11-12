"""Maps Anthropic SDK exceptions to `BrainError`, most specific class first.

Messages are for the user and the log. They never include the key or the raw
response body.
"""

from __future__ import annotations

import anthropic

from vision.core.interfaces import BrainError


def to_brain_error(exc: Exception) -> BrainError:
    match exc:
        case anthropic.EnforcedSpendLimitReachedError():
            return BrainError("credits", "The API spend limit for this account is reached.", False)
        case anthropic.RateLimitError():
            return BrainError("rate_limit", "Claude is rate limited right now.", True)
        case anthropic.AuthenticationError():
            return BrainError("auth", "The Anthropic API key was rejected.", False)
        case anthropic.PermissionDeniedError():
            return BrainError("auth", "The Anthropic API key may not use this model.", False)
        case anthropic.APIStatusError() if exc.status_code == 402 or exc.type == "billing_error":
            return BrainError("credits", "The Anthropic account has no credit left.", False)
        case anthropic.NotFoundError():
            return BrainError("bad_request", f"Claude does not know this model ({exc.message}).", False)
        case anthropic.BadRequestError() | anthropic.UnprocessableEntityError():
            return BrainError("bad_request", f"Claude rejected the request ({exc.message}).", False)
        case (
            anthropic.RequestTimeoutError()
            | anthropic.GatewayTimeoutError()
            | anthropic.DeadlineExceededError()
        ):
            return BrainError("timeout", "Claude took too long to answer.", True)
        case anthropic.InternalServerError():
            return BrainError("unavailable", f"Claude is unavailable (HTTP {exc.status_code}).", True)
        case anthropic.APIStatusError():
            return BrainError("internal", f"Claude returned HTTP {exc.status_code}.", False)
        case anthropic.APITimeoutError():
            return BrainError("timeout", "Claude took too long to answer.", True)
        case anthropic.APIConnectionError():
            return BrainError("offline", "Claude cannot be reached (no network?).", True)
        case _:
            name = type(exc).__name__
            return BrainError("internal", f"Unexpected error talking to Claude ({name}).", False)
