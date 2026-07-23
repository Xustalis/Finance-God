"""持仓服务 - CSV解析 + 资产匹配 + 未解析检测"""

import csv
import io
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import HoldingSnapshot
from app.models.instrument import Instrument


class HoldingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def import_csv(self, user_id: str, csv_content: str) -> dict:
        """解析CSV并创建持仓快照"""
        reader = csv.DictReader(io.StringIO(csv_content))
        positions = []
        unresolved = []

        for row in reader:
            symbol = (row.get("代码") or row.get("symbol") or "").strip()
            name = (row.get("资产名称") or row.get("name") or "").strip()
            qty = row.get("数量") or row.get("quantity") or "0"
            cost = row.get("成本价") or row.get("avg_cost") or "0"

            try:
                quantity = Decimal(qty)
                avg_cost = Decimal(cost)
            except Exception:
                continue

            # 尝试匹配资产
            instrument = await self._match_instrument(symbol, name)
            if instrument:
                market_value = quantity * avg_cost  # 简化: 用成本价代替市值
                positions.append({
                    "instrument_id": instrument["id"],
                    "symbol": instrument["symbol"],
                    "name": instrument["name"],
                    "quantity": float(quantity),
                    "avg_cost": float(avg_cost),
                    "market_value": float(market_value),
                    "currency": instrument["currency"],
                    "weight": 0,  # 后面计算
                })
            else:
                unresolved.append({
                    "raw_name": name,
                    "raw_symbol": symbol,
                    "quantity": float(quantity),
                    "estimated_value": float(quantity * avg_cost),
                    "match_candidates": [],
                })

        # 计算权重和未解析比例
        total_value = sum(p["market_value"] for p in positions)
        unresolved_value = sum(u["estimated_value"] for u in unresolved)
        grand_total = total_value + unresolved_value

        for p in positions:
            p["weight"] = p["market_value"] / grand_total if grand_total > 0 else 0

        unresolved_weight = unresolved_value / grand_total if grand_total > 0 else 0

        # 获取版本号
        result = await self.db.execute(
            select(func.max(HoldingSnapshot.version)).where(HoldingSnapshot.user_id == user_id)
        )
        max_version = result.scalar() or 0
        new_version = max_version + 1

        snapshot = HoldingSnapshot(
            id=str(uuid.uuid4()),
            user_id=user_id,
            version=new_version,
            source_type="csv_import",
            positions=positions,
            unresolved_positions=unresolved,
            unresolved_weight=Decimal(str(unresolved_weight)),
            total_market_value=Decimal(str(total_value)),
            total_cost_basis=Decimal(str(total_value)),
            cash_balance=Decimal("0"),
            valuation_as_of=datetime.now(timezone.utc),
        )
        self.db.add(snapshot)
        await self.db.flush()

        return self._to_dict(snapshot)

    async def create_manual(self, user_id: str, positions: list[dict]) -> dict:
        """手动创建持仓"""
        result = await self.db.execute(
            select(func.max(HoldingSnapshot.version)).where(HoldingSnapshot.user_id == user_id)
        )
        max_version = result.scalar() or 0
        new_version = max_version + 1

        total_value = sum(p.get("market_value", 0) for p in positions)
        for p in positions:
            p["weight"] = p.get("market_value", 0) / total_value if total_value > 0 else 0

        snapshot = HoldingSnapshot(
            id=str(uuid.uuid4()),
            user_id=user_id,
            version=new_version,
            source_type="manual",
            positions=positions,
            unresolved_positions=[],
            unresolved_weight=Decimal("0"),
            total_market_value=Decimal(str(total_value)),
            total_cost_basis=Decimal(str(total_value)),
            cash_balance=Decimal("0"),
            valuation_as_of=datetime.now(timezone.utc),
        )
        self.db.add(snapshot)
        await self.db.flush()
        return self._to_dict(snapshot)

    async def get_current(self, user_id: str) -> dict | None:
        result = await self.db.execute(
            select(HoldingSnapshot)
            .where(HoldingSnapshot.user_id == user_id)
            .order_by(HoldingSnapshot.version.desc())
            .limit(1)
        )
        snapshot = result.scalar_one_or_none()
        return self._to_dict(snapshot) if snapshot else None

    async def _match_instrument(self, symbol: str, name: str) -> dict | None:
        """匹配资产主数据"""
        if symbol:
            result = await self.db.execute(
                select(Instrument).where(
                    (Instrument.symbol == symbol) | (Instrument.symbol == f"{symbol}.SH") | (Instrument.symbol == f"{symbol}.SZ")
                )
            )
            inst = result.scalar_one_or_none()
            if inst:
                return {"id": inst.id, "symbol": inst.symbol, "name": inst.name, "currency": inst.currency}
        if name:
            result = await self.db.execute(
                select(Instrument).where(Instrument.name.ilike(f"%{name}%"))
            )
            inst = result.scalar_one_or_none()
            if inst:
                return {"id": inst.id, "symbol": inst.symbol, "name": inst.name, "currency": inst.currency}
        return None

    def _to_dict(self, snapshot: HoldingSnapshot) -> dict:
        return {
            "id": snapshot.id,
            "version": snapshot.version,
            "source_type": snapshot.source_type,
            "positions": snapshot.positions,
            "unresolved_positions": snapshot.unresolved_positions,
            "unresolved_weight": float(snapshot.unresolved_weight),
            "total_market_value": float(snapshot.total_market_value),
            "total_cost_basis": float(snapshot.total_cost_basis),
            "cash_balance": float(snapshot.cash_balance),
            "valuation_as_of": snapshot.valuation_as_of.isoformat() if snapshot.valuation_as_of else None,
        }
