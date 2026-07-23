"""画像服务 - 完整度/置信度计算 + 版本化"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import UserProfile
from app.models.audit_event import AuditEvent
from app.core.exceptions import ProfileIncompleteError
from app.core.versioning import generate_request_correlation_id


class ProfileService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def save_profile(self, user_id: str, data: dict) -> dict:
        """保存画像输入，计算完整度和置信度"""
        # 获取当前最大版本号
        result = await self.db.execute(
            select(func.max(UserProfile.version)).where(UserProfile.user_id == user_id)
        )
        max_version = result.scalar() or 0
        new_version = max_version + 1

        # 如果有旧版本，标记为 superseded
        if max_version > 0:
            old_result = await self.db.execute(
                select(UserProfile).where(
                    UserProfile.user_id == user_id,
                    UserProfile.version == max_version,
                )
            )
            old_profile = old_result.scalar_one_or_none()
            if old_profile and old_profile.status == "confirmed":
                old_profile.status = "superseded"

        # 计算完整度
        completeness = self._calculate_completeness(data)
        # 计算置信度
        confidence = self._calculate_confidence(data, "draft")

        profile = UserProfile(
            id=str(uuid.uuid4()),
            user_id=user_id,
            version=new_version,
            goals=data.get("goals", []),
            financial_constraints=data.get("financial_constraints", {}),
            stated_risk=data.get("stated_risk", {}),
            revealed_risk=data.get("revealed_risk", {}),
            behavioral_prefs=data.get("behavioral_prefs", {}),
            restrictions=data.get("restrictions", {}),
            completeness=completeness,
            confidence=confidence,
            status="draft",
        )
        self.db.add(profile)
        await self.db.flush()

        # 写审计
        audit = AuditEvent(
            id=str(uuid.uuid4()),
            event_type="profile_started",
            user_id=user_id,
            subject_type="profile",
            subject_id=profile.id,
            after_version=new_version,
            request_correlation_id=generate_request_correlation_id(),
            payload={"completeness": float(completeness)},
            actor="user",
        )
        self.db.add(audit)

        return self._to_dict(profile)

    async def confirm_profile(self, user_id: str, version: int) -> dict:
        """确认画像版本"""
        result = await self.db.execute(
            select(UserProfile).where(
                UserProfile.user_id == user_id,
                UserProfile.version == version,
            )
        )
        profile = result.scalar_one_or_none()
        if not profile:
            raise ProfileIncompleteError(0)

        if float(profile.completeness) < 0.6:
            raise ProfileIncompleteError(float(profile.completeness))

        profile.status = "confirmed"
        profile.confirmed_at = datetime.now(timezone.utc)
        profile.confidence = min(Decimal("1.0"), profile.confidence + Decimal("0.2"))
        await self.db.flush()

        # 写审计
        audit = AuditEvent(
            id=str(uuid.uuid4()),
            event_type="profile_confirmed",
            user_id=user_id,
            subject_type="profile",
            subject_id=profile.id,
            after_version=version,
            request_correlation_id=generate_request_correlation_id(),
            payload={"completeness": float(profile.completeness), "confidence": float(profile.confidence)},
            actor="user",
        )
        self.db.add(audit)

        return self._to_dict(profile)

    async def get_profile(self, user_id: str) -> dict | None:
        """优先返回最新已确认画像，否则返回最新版本"""
        result = await self.db.execute(
            select(UserProfile)
            .where(
                UserProfile.user_id == user_id,
                UserProfile.status == "confirmed",
            )
            .order_by(UserProfile.version.desc())
            .limit(1)
        )
        profile = result.scalar_one_or_none()
        if profile:
            return self._to_dict(profile)

        result = await self.db.execute(
            select(UserProfile)
            .where(UserProfile.user_id == user_id)
            .order_by(UserProfile.version.desc())
            .limit(1)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            return None
        return self._to_dict(profile)

    async def get_profile_by_version(self, user_id: str, version: int) -> dict | None:
        result = await self.db.execute(
            select(UserProfile).where(
                UserProfile.user_id == user_id,
                UserProfile.version == version,
            )
        )
        profile = result.scalar_one_or_none()
        return self._to_dict(profile) if profile else None

    def _calculate_completeness(self, data: dict) -> Decimal:
        """计算画像完整度"""
        score = Decimal("0")
        if data.get("goals"):
            score += Decimal("0.20")
        fc = data.get("financial_constraints", {})
        if fc and any(fc.get(k) for k in ["investable_amount", "emergency_fund", "near_term_cash_needs", "major_liabilities"]):
            score += Decimal("0.20")
        sr = data.get("stated_risk", {})
        if sr and any(sr.get(k) for k in ["loss_tolerance", "volatility_tolerance", "experience_years", "preference"]):
            score += Decimal("0.20")
        bp = data.get("behavioral_prefs", {})
        if bp and any(bp.get(k) for k in ["review_frequency", "drawdown_reaction"]):
            score += Decimal("0.10")
        r = data.get("restrictions", {})
        if r and any(r.get(k) for k in ["regions", "product_exclusions", "concentration_limits"]):
            score += Decimal("0.10")
        rr = data.get("revealed_risk", {})
        if rr and rr.get("inferred_tolerance") is not None:
            score += Decimal("0.20")
        return score

    def _calculate_confidence(self, data: dict, status: str) -> Decimal:
        """计算置信度"""
        base = Decimal("0.5")
        # 有来源信息加分
        sr = data.get("stated_risk", {})
        if sr.get("source"):
            base += Decimal("0.1")
        if sr.get("collected_at"):
            base += Decimal("0.05")
        rr = data.get("revealed_risk", {})
        if rr.get("source"):
            base += Decimal("0.1")
        # 确认加分
        if status == "confirmed":
            base += Decimal("0.2")
        return min(Decimal("1.0"), base)

    def _to_dict(self, profile: UserProfile) -> dict:
        return {
            "id": profile.id,
            "version": profile.version,
            "goals": profile.goals,
            "financial_constraints": profile.financial_constraints,
            "stated_risk": profile.stated_risk,
            "revealed_risk": profile.revealed_risk,
            "behavioral_prefs": profile.behavioral_prefs,
            "restrictions": profile.restrictions,
            "completeness": float(profile.completeness),
            "confidence": float(profile.confidence),
            "status": profile.status,
            "confirmed_at": profile.confirmed_at.isoformat() if profile.confirmed_at else None,
            "created_at": profile.created_at.isoformat() if profile.created_at else None,
        }
