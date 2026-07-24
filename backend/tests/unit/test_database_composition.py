import asyncio
from unittest.mock import AsyncMock, Mock

import server


def test_legacy_server_module_is_not_an_asgi_entrypoint() -> None:
    assert not hasattr(server, "app")


def test_workspace_uses_the_shared_application_session_factory(
    monkeypatch,
) -> None:
    session = Mock()
    shared_factory = Mock(return_value=session)
    monkeypatch.setattr(server, "create_db_session", shared_factory)

    assert server._workspace_session() is session
    shared_factory.assert_called_once_with()


def test_workflow_runtime_uses_the_shared_database_setting(monkeypatch) -> None:
    runtime = Mock()
    runtime.close = AsyncMock()
    factory = Mock(return_value=runtime)
    monkeypatch.setattr(
        server,
        "create_workflow_command_runtime_from_environment",
        factory,
    )

    lifespan = server.lifespan(server.finance_app)

    async def enter_and_exit() -> None:
        async with lifespan:
            pass

    asyncio.run(enter_and_exit())
    factory.assert_called_once_with(database_url=server.settings.database_url)
    runtime.close.assert_awaited_once_with()
