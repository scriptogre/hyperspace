"""
Global exception handlers.
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
    """
    Validation messages and submitted values from a failed form POST.
    """

    errors: dict[str, str] = field(default_factory=dict)
    data: dict[str, str] = field(default_factory=dict)

    def save(self, response: Response) -> None:
        """
        Write the errors and submitted values into a short-lived signed cookie.
        """
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
        """
        Read and delete the cookie so the errors show exactly once.
        """
        raw = request.cookies.get(FORM_ERRORS_COOKIE)
        if not raw:
            return cls()
        response.delete_cookie(FORM_ERRORS_COOKIE)
        try:
            payload = _serializer.loads(raw)
        except BadSignature:
            return cls()
        return cls(errors=payload.get("errors", {}), data=payload.get("data", {}))


class PlayerRequired(Exception):
    """
    Route requires a joined player.
    """


async def player_required_handler(request: Request, exception: Exception) -> Response:
    is_page_navigation = "text/html" in request.headers.get("accept", "")
    if is_page_navigation:
        return RedirectResponse("/", status_code=303)
    return Response(status_code=401)


async def not_found_handler(request: Request, exception: Exception) -> Response:
    return Response(status_code=404)


async def validation_error_handler(request: Request, exception: Exception) -> Response:
    """
    Turn a form validation error into a PRG redirect carrying the errors.
    """
    assert isinstance(exception, RequestValidationError)
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" not in content_type:
        return Response(status_code=422)

    errors = {error["loc"][-1]: error["msg"] for error in exception.errors()}
    data = {key: str(value) for key, value in (await request.form()).items()}

    response = RedirectResponse("/", status_code=303)
    FormErrors(errors=errors, data=data).save(response)
    return response
