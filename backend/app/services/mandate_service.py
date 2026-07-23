"""授权书服务 - 创建/激活/暂停/撤销 + 授权校验"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mandate import InvestmentMandate
from app.models.audit_event import AuditEvent
from app.core.exceptions import (
    MandateNotActiveError,
    AutonomyInsufficientError,
    ForbiddenError,
    ResourceNotFoundError,
)
from app.core.versioning import generate_request_correlation_id


class MandateService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_mandate(self, user_id: str, data: dict) -> dict:
        """创建授权书"""
        result = await self.db.execute(
            select(InvestmentMandate)
            .where(InvestmentMandate.user_id == user_id)
            .order_by(InvestmentMandate.version.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        new_version = (latest.version + 1) if latest else 1

        if latest and latest.status == "active":
            latest.status = "superseded"

        action = data.get("action", "draft")
        status = "active" if action == "activate" else "draft"

        mandate = InvestmentMandate(
            id=str(uuid.uuid4()),
            user_id=user_id,
            version=new_version,
            profile_version=data.get("profile_version", 1),
            goal_priorities=data.get("goal_priorities", []),
            risk_budget=data.get("risk_budget", {}),
            cash_boundary=data.get("cash_boundary", {}),
            asset_scope=data.get("asset_scope", {}),
            concentration_limits=data.get("concentration_limits", {}),
            rebalance_frequency=data.get("rebalance_frequency", "quarterly"),
            rebalance_threshold=data.get("rebalance_threshold", 0.05),
            autonomy_level=data.get("autonomy_level", "L0"),
            max_single_order_amount=data.get("max_single_order_amount"),
            valid_from=datetime.now(timezone.utc),
            valid_until=data.get("valid_until"),
            status=status,
        )
        self.db.add(mandate)
        await self.db.flush()

        audit = AuditEvent(
            id=str(uuid.uuid4()),
            event_type="mandate_activated" if status == "active" else "mandate_created",
            user_id=user_id,
            subject_type="mandate",
            subject_id=mandate.id,
            after_version=new_version,
            request_correlation_id=generate_request_correlation_id(),
            payload={"autonomy_level": mandate.autonomy_level},
            actor="user",
        )
        self.db.add(audit)

        return self._to_dict(mandate)

    async def get_active_mandate(self, user_id: str) -> dict | None:
        """获取当前有效授权书"""
        result = await self.db.execute(
            select(InvestmentMandate).where(
                InvestmentMandate.user_id == user_id,
                InvestmentMandate.status == "active",
            )
        )
        mandate = result.scalar_one_or_none()
        if not mandate:
            return None
        return self._to_dict(mandate)

    async def _get_owned_mandate(self, user_id: str, mandate_id: str) -> InvestmentMandate:
        result = await self.db.execute(
            select(InvestmentMandate).where(InvestmentMandate.id == mandate_id)
        )
        mandate = result.scalar_one_or_none()
        if not mandate:
            raise ResourceNotFoundError("授权书", mandate_id)
        if mandate.user_id != user_id:
            raise ForbiddenError("无权操作该授权书")
        return mandate

    async def pause_mandate(self, user_id: str, mandate_id: str) -> dict:
        """暂停授权书"""
        mandate = await self._get_owned_mandate(user_id, mandate_id)
        mandate.status = "paused"
        mandate.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return {"id": mandate.id, "status": "paused"}

    async def revoke_mandate(self, user_id: str, mandate_id: str, reason: str = "") -> dict:
        """撤销授权书"""
        mandate = await self._get_owned_mandate(user_id, mandate_id)
        mandate.status = "revoked"
        mandate.revoked_at = datetime.now(timezone.utc)
        mandate.revoke_reason = reason
        mandate.updated_at = datetime.now(timezone.utc)
        await self.db.flush()

        audit = AuditEvent(
            id=str(uuid.uuid4()),
            event_type="mandate_revoked",
            user_id=user_id,
            subject_type="mandate",
            subject_id=mandate.id,
            before_version=mandate.version,
            request_correlation_id=generate_request_correlation_id(),
            payload={"reason": reason},
            actor="user",
        )
        self.db.add(audit)

        return {"id": mandate.id, "status": "revoked"}

    async def validate_mandate(self, user_id: str, required_level: str = "L2") -> dict:
        """校验授权书是否有效"""
        mandate = await self.get_active_mandate(user_id)
        if not mandate:
            raise MandateNotActiveError("none")
        level_order = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
        if level_order.get(mandate["autonomy_level"], 0) < level_order.get(required_level, 2):
            raise AutonomyInsufficientError(mandate["autonomy_level"], required_level)
        return mandate

    def _to_dict(self, mandate: InvestmentMandate) -> dict:
        return {
            "id": mandate.id,
            "version": mandate.version,
            "profile_version": mandate.profile_version,
            "goal_priorities": mandate.goal_priorities,
            "risk_budget": mandate.risk_budget,
            "cash_boundary": mandate.cash_boundary,
            "asset_scope": mandate.asset_scope,
            "concentration_limits": mandate.concentration_limits,
            "rebalance_frequency": mandate.rebalance_frequency,
            "rebalance_threshold": float(mandate.rebalance_threshold),
            "autonomy_level": mandate.autonomy_level,
            "max_single_order_amount": float(mandate.max_single_order_amount) if mandate.max_single_order_amount else None,
            "valid_from": mandate.valid_from.isoformat() if mandate.valid_from else None,
            "valid_until": mandate.valid_until.isoformat() if mandate.valid_until else None,
            "status": mandate.status,
            "created_at": mandate.created_at.isoformat() if mandate.created_at else None,
        }
