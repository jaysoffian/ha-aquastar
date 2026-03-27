"""Exceptions for the Aquastar client."""


class AquastarError(Exception):
    """Base exception for all Aquastar client errors."""


class AuthenticationError(AquastarError):
    """Base class for authentication-related errors."""


class InvalidSecTokenError(AuthenticationError):
    """The sectoken was rejected by the server."""


class SessionExpiredError(AuthenticationError):
    """The session/JWT has expired and a new sectoken may be needed."""


class CannotConnectError(AquastarError):
    """Unable to connect to the Aquastar portal."""


class ApiError(AquastarError):
    """The portal returned an unexpected response."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_text: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


class DataParsingError(AquastarError):
    """Response data could not be parsed (XLS or HTML)."""
