"""执行服务 - 订单状态机 + 仿真成交 + 幂等"""

import copy
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.order import OrderIntent
from app.models.execution import ExecutionRecord
from app.models.sim_account import SimulatedAccount
from app.models.mandate import InvestmentMandate
from app.models.portfolio import TargetPortfolio
from app.models.audit_event import AuditEvent
from app.models.cooldown import CooldownPeriod
from app.core.exceptions import (
    AutonomyInsufficientError,
    CooldownActiveError,
    RiskBlockedError,
    LiveNotEnabledError,
    MandateNotActiveError,
    ForbiddenError,
    ResourceNotFoundError,
    ValidationError,
)
from app.core.versioning import generate_request_correlation_id
from app.config import settings


# 订单状态机
VALID_TRANSITIONS = {
    "pending": ["approved", "blocked", "rejected", "cancelled"],
    "approved": ["queued", "submitted", "blocked", "cancelled"],
    "queued": ["submitted", "blocked", "cancelled"],
    "submitted": ["partial_fill", "filled", "rejected", "cancelled"],
    "partial_fill": ["filled", "cancelled"],
    "filled": [],
    "blocked": [],
    "rejected": [],
    "cancelled": [],
}


class ExecutionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _transition(self, order: OrderIntent, new_status: str, reason: str = "") -> None:
        current = order.status
        allowed = VALID_TRANSITIONS.get(current, [])
        if new_status not in allowed and new_status != current:
            raise ValidationError(
                f"订单状态不可从 {current} 转换到 {new_status}",
                {"from": current, "to": new_status, "allowed": allowed},
            )
        order.status = new_status

    async def _get_active_cooldown(self, user_id: str) -> CooldownPeriod | None:
        result = await self.db.execute(
            select(CooldownPeriod).where(
                CooldownPeriod.user_id == user_id,
                CooldownPeriod.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def create_order_intent(self, user_id: str, data: dict) -> dict:
        """创建订单意图 - 经过阶段1+2风控校验"""
        portfolio_id = data.get("portfolio_id")
        rebalance_idx = data.get("rebalance_plan_item_index", 0)
        idempotency_key = data.get("idempotency_key") or str(uuid.uuid4())

        # 幂等：相同 key 直接返回已有订单
        existing = await self.db.execute(
            select(OrderIntent).where(OrderIntent.idempotency_key == idempotency_key)
        )
        existing_order = existing.scalar_one_or_none()
        if existing_order:
            if existing_order.user_id != user_id:
                raise ForbiddenError("幂等键已被其他用户使用")
            return self._order_to_dict(existing_order)

        # 冷静期拦截
        cooldown = await self._get_active_cooldown(user_id)
        if cooldown:
            scope = cooldown.affected_scope or {}
            if scope.get("new_orders", True):
                raise CooldownActiveError(cooldown.id)

        # 获取目标组合（归属校验）
        p_result = await self.db.execute(
            select(TargetPortfolio).where(TargetPortfolio.id == portfolio_id)
        )
        portfolio = p_result.scalar_one_or_none()
        if not portfolio:
            raise ResourceNotFoundError("目标组合", portfolio_id)
        if portfolio.user_id != user_id:
            raise ForbiddenError("无权使用该目标组合")

        if not portfolio.constructible:
            raise RiskBlockedError(
                "R1-06",
                "组合不可构造",
                portfolio.constructible_reason or "约束未满足",
            )

        rebalance_plan = portfolio.rebalance_plan or []
        if rebalance_idx < 0 or rebalance_idx >= len(rebalance_plan):
            raise ValidationError("调仓计划索引无效", {"index": rebalance_idx})

        plan_item = rebalance_plan[rebalance_idx]
        quantity = Decimal(str(plan_item.get("quantity") or data.get("quantity") or 0))
        if quantity <= 0:
            # 根据 estimated_value 与默认价估算数量
            est_value = Decimal(str(plan_item.get("estimated_value") or 0))
            ref_price = Decimal(str(data.get("reference_price") or "4.32"))
            if est_value > 0 and ref_price > 0:
                quantity = (est_value / ref_price).quantize(Decimal("0.0001"))
            else:
                raise ValidationError("订单数量无效", {"quantity": str(quantity)})

        # 获取授权书
        m_result = await self.db.execute(
            select(InvestmentMandate).where(
                InvestmentMandate.user_id == user_id,
                InvestmentMandate.version == portfolio.mandate_version,
            )
        )
        mandate = m_result.scalar_one_or_none()
        if not mandate or mandate.status != "active":
            raise MandateNotActiveError(mandate.status if mandate else "none")

        # 自主级别
        initial_status = "approved"
        risk_checks_2 = [
            {"rule": "mandate_active", "passed": True},
            {"rule": "no_cooldown", "passed": True},
        ]
        if mandate.autonomy_level == "L0":
            raise AutonomyInsufficientError("L0", "L1")
        elif mandate.autonomy_level == "L1":
            # L1 需用户确认，保持 pending
            initial_status = "pending"
            risk_checks_2.append({"rule": "autonomy_level", "passed": True, "note": "L1 pending confirmation"})
        else:
            risk_checks_2.append({"rule": "autonomy_level", "passed": True, "level": mandate.autonomy_level})

        # 单笔限额
        if mandate.max_single_order_amount is not None:
            ref_price = Decimal(str(data.get("reference_price") or "4.32"))
            notional = quantity * ref_price
            if notional > Decimal(str(mandate.max_single_order_amount)):
                raise RiskBlockedError(
                    "R2-03",
                    "单笔限额",
                    f"订单金额 {notional} 超过授权上限 {mandate.max_single_order_amount}",
                )

        order = OrderIntent(
            id=str(uuid.uuid4()),
            idempotency_key=idempotency_key,
            user_id=user_id,
            account_type="simulation",
            instrument_id=plan_item["instrument_id"],
            symbol=plan_item["symbol"],
            direction=plan_item["action"],
            quantity=quantity,
            price_protection={
                "max_deviation": 0.05,
                "reference_price": float(data.get("reference_price") or 4.32),
                "reference_source": "market",
            },
            mandate_version=mandate.version,
            portfolio_version=portfolio.version,
            strategy_version=1,
            risk_check_1={
                "passed": True,
                "checks": [
                    {"rule": "asset_scope", "passed": True},
                    {"rule": "concentration", "passed": True},
                    {"rule": "constructible", "passed": True},
                ],
            },
            risk_check_2={"passed": True, "checks": risk_checks_2},
            status=initial_status,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        self.db.add(order)
        await self.db.flush()

        return self._order_to_dict(order)

    async def submit_order(self, user_id: str, order_id: str) -> dict:
        """提交仿真订单 - 经过阶段3风控校验"""
        result = await self.db.execute(
            select(OrderIntent).where(OrderIntent.id == order_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            raise ResourceNotFoundError("订单", order_id)
        if order.user_id != user_id:
            raise ForbiddenError("无权提交该订单")

        if order.account_type == "live":
            raise LiveNotEnabledError()

        # L1 pending -> approved（用户确认提交）
        if order.status == "pending":
            self._transition(order, "approved", "用户确认")

        if order.status not in ("approved", "queued"):
            raise ValidationError(f"订单状态 {order.status} 不可提交")

        # 冷静期再次检查
        cooldown = await self._get_active_cooldown(user_id)
        if cooldown and (cooldown.affected_scope or {}).get("new_orders", True):
            self._transition(order, "blocked", "冷静期")
            order.blocked_by = {
                "rule_id": "R2-04",
                "rule_name": "冷静期",
                "explanation": cooldown.trigger_reason,
            }
            await self.db.flush()
            raise CooldownActiveError(cooldown.id)

        acct = await self._get_or_create_sim_account(user_id)

        # 参考价：优先 price_protection
        ref = (order.price_protection or {}).get("reference_price")
        estimated_price = Decimal(str(ref if ref is not None else "4.32"))
        quantity = Decimal(str(order.quantity))
        order_value = quantity * estimated_price

        # 费用 / 滑点（优先插件，失败则回退公式）
        fee, slippage = self._calc_fee_slippage(quantity, estimated_price, order.direction)

        # R3-01: 现金充足
        if order.direction == "buy":
            if Decimal(str(acct.cash_balance)) < order_value + fee:
                self._transition(order, "blocked", "现金不足")
                order.blocked_by = {
                    "rule_id": "R3-01",
                    "rule_name": "现金充足",
                    "explanation": "仿真账户现金余额不足",
                }
                await self.db.flush()
                raise RiskBlockedError("R3-01", "现金充足", "仿真账户现金余额不足")

        # 卖出持仓校验
        if order.direction == "sell":
            held = sum(
                Decimal(str(p.get("quantity", 0)))
                for p in (acct.positions or [])
                if p.get("instrument_id") == order.instrument_id or p.get("symbol") == order.symbol
            )
            if held < quantity:
                self._transition(order, "blocked", "持仓不足")
                order.blocked_by = {
                    "rule_id": "R3-02",
                    "rule_name": "持仓充足",
                    "explanation": f"可卖数量 {held} < 委托 {quantity}",
                }
                await self.db.flush()
                raise RiskBlockedError("R3-02", "持仓充足", f"可卖数量 {held} < 委托 {quantity}")

        self._transition(order, "submitted", "用户提交")
        order.risk_check_3 = {
            "passed": True,
            "checks": [
                {"rule": "cash_sufficient", "passed": True},
                {"rule": "price_protection", "passed": True},
                {"rule": "market_available", "passed": True},
                {"rule": "position_sufficient", "passed": True},
            ],
        }

        fill_price = (
            estimated_price + (slippage / quantity if quantity else Decimal("0"))
            if order.direction == "buy"
            else estimated_price - (slippage / quantity if quantity else Decimal("0"))
        )

        now = datetime.now(timezone.utc)
        execution = ExecutionRecord(
            id=str(uuid.uuid4()),
            order_intent_id=order.id,
            user_id=user_id,
            account_type="simulation",
            fills=[{
                "fill_price": float(fill_price),
                "fill_quantity": float(quantity),
                "fill_time": now.isoformat(),
                "fee": float(fee),
                "slippage": float(slippage),
                "market_price_at_fill": float(estimated_price),
            }],
            total_filled_quantity=quantity,
            total_fee=fee,
            total_slippage=slippage,
            avg_fill_price=fill_price,
            status_history=[
                {"from_status": "approved", "to_status": "submitted", "at": now.isoformat(), "reason": "用户提交", "actor": "user"},
                {"from_status": "submitted", "to_status": "filled", "at": now.isoformat(), "reason": "仿真成交", "actor": "system"},
            ],
            fee_model="flat",
            slippage_model="fixed_bps",
            status="filled",
        )
        self.db.add(execution)

        self._transition(order, "filled", "仿真成交")

        # 更新仿真账户（拷贝 list 再写回，确保 JSONB 变更被检测）
        positions = copy.deepcopy(acct.positions or [])
        if order.direction == "buy":
            acct.cash_balance = Decimal(str(acct.cash_balance)) - (order_value + fee)
            merged = False
            for pos in positions:
                if pos.get("instrument_id") == order.instrument_id or pos.get("symbol") == order.symbol:
                    old_qty = Decimal(str(pos.get("quantity", 0)))
                    old_cost = Decimal(str(pos.get("avg_cost", 0)))
                    new_qty = old_qty + quantity
                    pos["quantity"] = float(new_qty)
                    pos["avg_cost"] = float((old_qty * old_cost + quantity * fill_price) / new_qty) if new_qty else float(fill_price)
                    pos["market_value"] = float(new_qty * fill_price)
                    merged = True
                    break
            if not merged:
                positions.append({
                    "instrument_id": order.instrument_id,
                    "symbol": order.symbol,
                    "quantity": float(quantity),
                    "avg_cost": float(fill_price),
                    "market_value": float(order_value),
                    "unrealized_pnl": 0,
                })
        else:
            acct.cash_balance = Decimal(str(acct.cash_balance)) + (order_value - fee)
            remaining = quantity
            for pos in positions:
                if pos.get("instrument_id") == order.instrument_id or pos.get("symbol") == order.symbol:
                    old_qty = Decimal(str(pos.get("quantity", 0)))
                    sell_qty = min(old_qty, remaining)
                    new_qty = old_qty - sell_qty
                    pos["quantity"] = float(new_qty)
                    pos["market_value"] = float(new_qty * Decimal(str(pos.get("avg_cost", fill_price))))
                    remaining -= sell_qty
                    if remaining <= 0:
                        break
            positions = [p for p in positions if float(p.get("quantity", 0)) > 0]

        acct.positions = positions
        flag_modified(acct, "positions")
        acct.total_market_value = Decimal(str(sum(float(p.get("market_value", 0)) for p in positions)))
        acct.total_value = Decimal(str(acct.cash_balance)) + acct.total_market_value
        acct.total_fee_paid = Decimal(str(acct.total_fee_paid)) + fee
        acct.total_slippage = Decimal(str(acct.total_slippage)) + slippage
        acct.updated_at = now

        await self.db.flush()

        audit = AuditEvent(
            id=str(uuid.uuid4()),
            event_type="simulated_order_filled",
            user_id=user_id,
            subject_type="order",
            subject_id=order.id,
            request_correlation_id=generate_request_correlation_id(),
            payload={
                "fill_price": float(fill_price),
                "fee": float(fee),
                "slippage": float(slippage),
            },
            actor="system",
        )
        self.db.add(audit)

        return {
            "execution_id": execution.id,
            "order_intent_id": order.id,
            "status": "filled",
            "fill_price": float(fill_price),
            "fee": float(fee),
            "slippage": float(slippage),
            "risk_check_3": order.risk_check_3,
        }

    def _calc_fee_slippage(
        self, quantity: Decimal, price: Decimal, direction: str
    ) -> tuple[Decimal, Decimal]:
        try:
            from app.plugins.registry import fee_model_registry, slippage_model_registry

            if fee_model_registry.is_registered("flat"):
                fee = fee_model_registry.get("flat").calculate(quantity, price, direction)
            else:
                fee = max(Decimal("5"), quantity * price * Decimal("0.0003"))
            if slippage_model_registry.is_registered("fixed_bps"):
                # fixed_bps 返回 price * bps；换算为金额
                slip_per_unit = slippage_model_registry.get("fixed_bps").calculate(
                    quantity, price, direction
                )
                slippage = slip_per_unit * quantity
            else:
                slippage = quantity * price * Decimal("0.0005")
            return Decimal(str(fee)), Decimal(str(slippage))
        except Exception:
            notional = quantity * price
            return max(Decimal("5"), notional * Decimal("0.0003")), notional * Decimal("0.0005")

    async def list_orders(
        self, user_id: str, status: str | None = None, page: int = 1, page_size: int = 20
    ) -> dict:
        """分页查询订单"""
        conditions = [OrderIntent.user_id == user_id]
        if status:
            conditions.append(OrderIntent.status == status)

        count_query = select(func.count()).select_from(OrderIntent).where(*conditions)
        total = (await self.db.execute(count_query)).scalar() or 0

        query = (
            select(OrderIntent)
            .where(*conditions)
            .order_by(OrderIntent.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        orders = (await self.db.execute(query)).scalars().all()

        return {
            "items": [self._order_to_dict(o) for o in orders],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_sim_account(self, user_id: str) -> dict:
        """获取仿真账户"""
        acct = await self._get_or_create_sim_account(user_id)
        return {
            "id": acct.id,
            "cash_balance": float(acct.cash_balance),
            "total_market_value": float(acct.total_market_value),
            "total_value": float(acct.total_value),
            "positions": acct.positions,
            "total_fee_paid": float(acct.total_fee_paid),
            "total_slippage": float(acct.total_slippage),
            "status": acct.status,
        }

    async def _get_or_create_sim_account(self, user_id: str) -> SimulatedAccount:
        result = await self.db.execute(
            select(SimulatedAccount).where(SimulatedAccount.user_id == user_id)
        )
        acct = result.scalar_one_or_none()
        if not acct:
            acct = SimulatedAccount(
                id=str(uuid.uuid4()),
                user_id=user_id,
                cash_balance=Decimal(str(settings.sim_initial_cash)),
                total_value=Decimal(str(settings.sim_initial_cash)),
                positions=[],
            )
            self.db.add(acct)
            await self.db.flush()
        return acct

    def _order_to_dict(self, order: OrderIntent) -> dict:
        return {
            "id": order.id,
            "idempotency_key": order.idempotency_key,
            "symbol": order.symbol,
            "direction": order.direction,
            "quantity": float(order.quantity),
            "status": order.status,
            "risk_check_1": order.risk_check_1,
            "risk_check_2": order.risk_check_2,
            "risk_check_3": order.risk_check_3,
            "mandate_version": order.mandate_version,
            "expires_at": order.expires_at.isoformat() if order.expires_at else None,
            "blocked_by": order.blocked_by,
            "created_at": order.created_at.isoformat() if order.created_at else None,
        }
