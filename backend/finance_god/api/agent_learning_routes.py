"""Authenticated read-only routes for continuous-learning status."""

from __future__ import annotations

from collections.abc import Callable

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from finance_god.api.auth import AuthenticationError, OwnerResolver
from finance_god.application.agent_learning_summary import AgentLearningSummaryReader

SummaryReaderProvider = Callable[[], AgentLearningSummaryReader]


def create_agent_learning_routes(
    *,
    owner_resolver: OwnerResolver,
    reader_provider: SummaryReaderProvider,
) -> list[Route]:
    async def summary(request: Request) -> JSONResponse:
        try:
            owner_id = (await owner_resolver(request)).strip()
            if not owner_id or len(owner_id) > 160:
                raise AuthenticationError("authenticated owner is required")
            result = reader_provider().read()
            return JSONResponse(result.model_dump(mode="json"))
        except AuthenticationError as error:
            return JSONResponse(
                {"error": {"code": "UNAUTHORIZED", "message": str(error)}},
                status_code=401,
            )

    return [Route("/summary", summary, methods=["GET"])]


__all__ = ["create_agent_learning_routes"]
