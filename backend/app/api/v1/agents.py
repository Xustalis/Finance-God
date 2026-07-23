"""Agent 路由 - 状态/健康检查/执行"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.agents.base import AgentInput
from app.core.response import ApiResponse
from app.core.security import get_current_user_id
from app.plugins.registry import agent_registry

router = APIRouter()


@router.get("/")
async def list_agents(user_id: str = Depends(get_current_user_id)):
    statuses = []
    for name in agent_registry.list_available():
        agent = agent_registry.get(name)
        health = await agent.health_check()
        statuses.append(
            {
                "name": agent.name,
                "capabilities": agent.capabilities,
                "health": health,
            }
        )
    return ApiResponse.ok(statuses)


@router.get("/{name}/health")
async def agent_health(
    name: str,
    user_id: str = Depends(get_current_user_id),
):
    if not agent_registry.is_registered(name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{name}' 未注册",
        )
    agent = agent_registry.get(name)
    health = await agent.health_check()
    return ApiResponse.ok({"name": agent.name, "health": health})


@router.post("/{name}/execute")
async def execute_agent(
    name: str,
    data: dict,
    user_id: str = Depends(get_current_user_id),
):
    if not agent_registry.is_registered(name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{name}' 未注册",
        )
    agent = agent_registry.get(name)
    agent_input = AgentInput(
        request_id=str(uuid.uuid4()),
        user_id=user_id,
        context=data.get("context", {}),
    )
    output = await agent.execute(agent_input)
    return ApiResponse.ok(output.model_dump())
