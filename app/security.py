"""Make sure callers come through RapidAPI (which handles keys, quotas, billing)."""
import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings


def verify_rapidapi(
    settings: Annotated[Settings, Depends(get_settings)],
    # include_in_schema=False: this header is set by RapidAPI's gateway, so customers must not see it in the docs.
    x_rapidapi_proxy_secret: Annotated[str | None, Header(include_in_schema=False)] = None,
) -> None:
    if not settings.rapidapi_proxy_secret:
        return  # local dev: no secret configured
    if not x_rapidapi_proxy_secret or not secrets.compare_digest(
        x_rapidapi_proxy_secret, settings.rapidapi_proxy_secret
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Direct access is not allowed. Subscribe via RapidAPI.",
        )
