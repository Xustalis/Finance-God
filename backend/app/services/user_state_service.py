"""用户心智状态服务 - 心智快照 + 偏差检测 + 冷静期判定"""

import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_state import UserStateSnapshot
from app.models.cooldown import CooldownPeriod
from app.core.exceptions import ForbiddenError, ResourceNotFoundError


# 偏差检测阈值（可被进化层调整）
ANXIETY_THRESHOLD = 0.7
GREED_THRESHOLD = 0.7
IMPULSIVITY_THRESHOLD = 0.8


class UserStateService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_snapshot(self, user_id: str, data: dict) -> dict:
        """创建心智状态快照"""
        result = await self.db.execute(
            select(UserStateSnapshot)
            .where(UserStateSnapshot.user_id == user_id)
            .order_by(UserStateSnapshot.version.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        new_version = (latest.version + 1) if latest else 1

        mental_state = data.get("mental_state", {})
        cognitive_biases = data.get("cognitive_biases", [])
        signal_sources = data.get("signal_sources", [])

        confidence = self._calculate_confidence(signal_sources)

        snapshot = UserStateSnapshot(
            id=str(uuid.uuid4()),
            user_id=user_id,
            version=new_version,
            mental_state=mental_state,
            cognitive_biases=cognitive_biases,
            signal_sources=signal_sources,
            consent_scope=data.get("consent_scope", ""),
            confidence=confidence,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            user_confirmation="pending",
        )
        self.db.add(snapshot)
        await self.db.flush()
        return self._to_dict(snapshot)

    async def confirm_state(
        self,
        user_id: str,
        snapshot_id: str,
        action: str,
        feedback: str | None = None,
    ) -> dict:
        """确认/修正/拒绝心智状态"""
        result = await self.db.execute(
            select(UserStateSnapshot).where(UserStateSnapshot.id == snapshot_id)
        )
        snapshot = result.scalar_one_or_none()
        if not snapshot:
            raise ResourceNotFoundError("心智状态快照", snapshot_id)
        if snapshot.user_id != user_id:
            raise ForbiddenError("无权操作该心智状态快照")

        action_map = {"confirm": "confirmed", "correct": "corrected", "reject": "rejected"}
        snapshot.user_confirmation = action_map.get(action, "confirmed")
        if feedback:
            snapshot.user_feedback = feedback

        cooldown_triggered = False
        cooldown_id = None
        if action == "confirm":
            mental = snapshot.mental_state or {}
            anxiety = float(mental.get("anxiety_level", 0) or 0)
            impulsivity = float(mental.get("impulsivity", 0) or 0)
            greed = float(mental.get("greed_level", 0) or 0)

            if anxiety >= ANXIETY_THRESHOLD:
                cooldown = await self._create_cooldown(
                    user_id,
                    snapshot.id,
                    f"焦虑水平 {anxiety:.2f} 超过阈值 {ANXIETY_THRESHOLD}",
                    "anxiety",
                )
                cooldown_triggered = True
                cooldown_id = cooldown["id"]
            elif impulsivity >= IMPULSIVITY_THRESHOLD:
                cooldown = await self._create_cooldown(
                    user_id,
                    snapshot.id,
                    f"冲动水平 {impulsivity:.2f} 超过阈值 {IMPULSIVITY_THRESHOLD}",
                    "impulsivity",
                )
                cooldown_triggered = True
                cooldown_id = cooldown["id"]
            elif greed >= GREED_THRESHOLD:
                cooldown = await self._create_cooldown(
                    user_id,
                    snapshot.id,
                    f"贪婪水平 {greed:.2f} 超过阈值 {GREED_THRESHOLD}",
                    "greed",
                )
                cooldown_triggered = True
                cooldown_id = cooldown["id"]

        await self.db.flush()
        return {
            "state_snapshot_id": snapshot.id,
            "user_confirmation": snapshot.user_confirmation,
            "cooldown_triggered": cooldown_triggered,
            "cooldown_id": cooldown_id,
            # 冷静期生效时暂停新订单与策略生成
            "affected_scope": (
                {"new_orders": True, "strategy_generation": True, "review_required": True}
                if cooldown_triggered
                else None
            ),
        }

    async def get_latest_snapshot(self, user_id: str) -> dict | None:
        result = await self.db.execute(
            select(UserStateSnapshot)
            .where(UserStateSnapshot.user_id == user_id)
            .order_by(UserStateSnapshot.version.desc())
            .limit(1)
        )
        snapshot = result.scalar_one_or_none()
        return self._to_dict(snapshot) if snapshot else None

    async def has_active_cooldown(self, user_id: str) -> bool:
        """检查是否有活跃冷静期"""
        result = await self.db.execute(
            select(CooldownPeriod).where(
                CooldownPeriod.user_id == user_id,
                CooldownPeriod.status == "active",
            )
        )
        return result.scalar_one_or_none() is not None

    async def get_active_cooldown(self, user_id: str) -> dict | None:
        result = await self.db.execute(
            select(CooldownPeriod).where(
                CooldownPeriod.user_id == user_id,
                CooldownPeriod.status == "active",
            )
        )
        cd = result.scalar_one_or_none()
        if not cd:
            return None
        return {
            "id": cd.id,
            "trigger_reason": cd.trigger_reason,
            "cooldown_type": cd.cooldown_type,
            "affected_scope": cd.affected_scope,
            "recovery_conditions": cd.recovery_conditions,
            "status": cd.status,
            "started_at": cd.started_at.isoformat() if cd.started_at else None,
        }

    async def resolve_cooldown(
        self,
        user_id: str,
        cooldown_id: str,
        resolved_by: str = "user_confirmation",
    ) -> dict:
        """解除冷静期"""
        result = await self.db.execute(
            select(CooldownPeriod).where(CooldownPeriod.id == cooldown_id)
        )
        cd = result.scalar_one_or_none()
        if not cd:
            raise ResourceNotFoundError("冷静期", cooldown_id)
        if cd.user_id != user_id:
            raise ForbiddenError("无权操作该冷静期")
        cd.status = "resolved"
        cd.resolved_at = datetime.now(timezone.utc)
        cd.resolved_by = resolved_by
        await self.db.flush()
        return {"id": cd.id, "status": "resolved"}

    async def _create_cooldown(
        self, user_id: str, snapshot_id: str, reason: str, cd_type: str
    ) -> dict:
        cd = CooldownPeriod(
            id=str(uuid.uuid4()),
            user_id=user_id,
            trigger_state_snapshot_id=snapshot_id,
            trigger_reason=reason,
            cooldown_type=cd_type,
            # new_orders=True 表示暂停新订单
            affected_scope={
                "new_orders": True,
                "strategy_generation": True,
                "review_required": True,
            },
            recovery_conditions={
                "user_confirmation": True,
                "review_completed": False,
                "waiting_period_hours": 24,
            },
            status="active",
        )
        self.db.add(cd)
        await self.db.flush()
        return {"id": cd.id, "status": "active"}

    def _calculate_confidence(self, signal_sources: list) -> Decimal:
        if not signal_sources:
            return Decimal("0.3")
        return min(Decimal("1.0"), Decimal("0.5") + Decimal(str(len(signal_sources) * 0.15)))

    def _to_dict(self, snapshot: UserStateSnapshot) -> dict:
        return {
            "id": snapshot.id,
            "version": snapshot.version,
            "mental_state": snapshot.mental_state,
            "cognitive_biases": snapshot.cognitive_biases,
            "signal_sources": snapshot.signal_sources,
            "confidence": float(snapshot.confidence),
            "expires_at": snapshot.expires_at.isoformat() if snapshot.expires_at else None,
            "user_confirmation": snapshot.user_confirmation,
            "user_feedback": snapshot.user_feedback,
            "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        }
