"""Global exception handlers.

The join form is a plain, boosted form (htmx `hx-boost`). On a validation error
we use the Post/Redirect/Get pattern: pack the errors and the submitted values
into a short-lived signed cookie, then 303 back to `/`. The GET reads them via
the `get_form_errors` dependency and re-renders the form with the message and the
user's input intact. htmx follows the redirect and morphs the result, so it feels
inline even though it is a full round trip.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeSerializer

from app.config import settings

FORM_ERRORS_COOKIE = "form_errors"
COOKIE_MAX_AGE = 10  # seconds, just long enough to survive the redirect

_serializer = URLSafeSerializer(settings.SECRET_KEY)


@dataclass
class FormErrors:
    """Validation messages and submitted values from a failed form POST."""

    errors: dict[str, str] = field(default_factory=dict)
    data: dict[str, str] = field(default_factory=dict)

    def save(self, response: Response) -> None:
        payload = _serializer.dumps({"errors": self.errors, "data": self.data})
        response.set_cookie(
            FORM_ERRORS_COOKIE,
            payload,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
        )

    @classmethod
    def pop(cls, request: Request, response: Response) -> FormErrors:
        """Read and delete the cookie so the errors show exactly once."""
        raw = request.cookies.get(FORM_ERRORS_COOKIE)
        if not raw:
            return cls()
        response.delete_cookie(FORM_ERRORS_COOKIE)
        try:
            payload = _serializer.loads(raw)
        except BadSignature:
            return cls()
        return cls(errors=payload.get("errors", {}), data=payload.get("data", {}))


async def validation_error_handler(request: Request, exception: Exception) -> Response:
    """Turn a form validation error into a PRG redirect carrying the errors."""
    assert isinstance(exception, RequestValidationError)
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" not in content_type:
        return Response(status_code=422)

    errors = {error["loc"][-1]: error["msg"] for error in exception.errors()}
    data = {key: str(value) for key, value in (await request.form()).items()}

    response = RedirectResponse("/", status_code=303)
    FormErrors(errors=errors, data=data).save(response)
    return response
