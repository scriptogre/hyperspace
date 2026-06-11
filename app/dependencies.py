"""
FastAPI dependencies for the hyperspace app.
"""

import uuid

from fastapi import Request, Response

COOKIE_NAME = "hyperspace_id"


async def get_session_id(request: Request, response: Response) -> str:
    """Return the caller's session UUID, issuing a new cookie if they are new."""
    session_id = request.cookies.get(COOKIE_NAME)
    if not session_id:
        session_id = str(uuid.uuid4())
        response.set_cookie(
            COOKIE_NAME,
            session_id,
            max_age=365 * 24 * 3600,
            samesite="lax",
            httponly=False,
        )
    return session_id
