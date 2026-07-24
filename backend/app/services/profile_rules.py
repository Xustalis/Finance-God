from dataclasses import dataclass

from app.services.ai_orchestrator import PROFILE_DIMENSIONS

DIRECTIONS = (
    "cash_fixed_income",
    "public_funds",
    "equities",
    "alternatives",
    "long_term_insurance",
)

RISK_EVIDENCE_WEIGHTS = {
    "risk_tolerance": 18,
    "liquidity_need": -12,
    "investment_goal": 8,
    "loss_behavior": 14,
    "investment_knowledge": 8,
    "income_stability": 10,
}

HORIZON_LABELS = {
    "under_1_year": "1年以内",
    "1_3_years": "1至3年",
    "3_5_years": "3至5年",
    "5_plus_years": "5年以上",
}

EXPERIENCE_LABELS = {
    "none": "暂无投资经验",
    "beginner": "初步投资经验",
    "intermediate": "中等投资经验",
    "advanced": "较丰富投资经验",
}

LOSS_REACTION_LABELS = {
    "sell_all": "全部卖出",
    "reduce": "减少持仓",
    "hold": "继续持有",
    "buy_more": "分批增加投入",
}

ARCHETYPE_TITLES = {
    "STEADY_GUARDIAN": "稳健守望者",
    "BALANCED_NAVIGATOR": "均衡领航者",
    "LONG_HORIZON_BUILDER": "长期成长建设者",
}


@dataclass(frozen=True)
class ProfileAssessment:
    archetype_code: str
    archetype_title: str
    risk_level: str
    loss_tolerance_percent: int
    dimension_scores: dict[str, int]
    summary: dict


def objective_text(objective: dict) -> tuple[str, str, str, int]:
    horizon = HORIZON_LABELS.get(objective.get("fund_horizon"), "资金期限尚待确认")
    experience = EXPERIENCE_LABELS.get(
        objective.get("investment_experience"), "投资经验尚待确认"
    )
    loss_reaction = LOSS_REACTION_LABELS.get(
        objective.get("loss_reaction"), "亏损反应尚待确认"
    )
    reserve_months = max(0, int(objective.get("emergency_fund_months", 0)))
    return horizon, experience, loss_reaction, reserve_months


def report_summary(objective: dict, loss: int, low_confidence: list[str]) -> dict:
    horizon, experience, loss_reaction, reserve_months = objective_text(objective)
    is_minor = objective.get("age_range") == "minor"
    traits = [
        "处于金融启蒙阶段" if is_minor else f"资金计划为{horizon}",
        f"已准备约{reserve_months}个月应急资金",
        f"面对亏损倾向{loss_reaction}",
        experience,
        "重视风险边界与分散配置",
    ]
    risk_notice = (
        "未成年人画像仅用于金融教育，不构成可执行投资建议；任何投资都可能亏损，也不保证收益。"
        if is_minor
        else "任何投资都可能发生本金亏损；本画像只用于教育和方向参考，不保证收益。"
    )
    reasoning = [
        f"你预计这笔资金的使用期限为{horizon}，规则据此判断可承受的资产波动周期。",
        f"你的应急资金可覆盖约{reserve_months}个月，规则据此评估临时用款对投资计划的影响。",
        f"历史亏损情境下你倾向{loss_reaction}，该选择用于判断阶段性回撤时的行为承受力。",
        f"你目前具备{experience}，规则据此限制需要较高研究能力的方向占比。",
        f"综合客观信息后，规则采用约{loss}%的阶段性亏损承受阈值；这不是损失上限，也不代表收益预期。",
    ]
    return {
        "traits": traits,
        "risk_notice": risk_notice,
        "reasoning": reasoning,
        "low_confidence": low_confidence,
    }


def assess_profile(
    objective: dict,
    conversation_scores: dict,
    profile_evidence: dict,
    skipped_dimensions: list[str],
) -> ProfileAssessment:
    risk = 45
    risk += {"sell_all": -25, "reduce": -12, "hold": 10, "buy_more": 20}.get(objective.get("loss_reaction"), 0)
    risk += {"under_1_year": -20, "1_3_years": -8, "3_5_years": 5, "5_plus_years": 15}.get(objective.get("fund_horizon"), 0)
    risk += min(int(objective.get("emergency_fund_months", 0)), 12) - 6
    risk += {"none": -10, "beginner": -5, "intermediate": 5, "advanced": 12}.get(objective.get("investment_experience"), 0)
    risk += sum(
        round(float(profile_evidence.get(dimension, 0.0)) * weight)
        for dimension, weight in RISK_EVIDENCE_WEIGHTS.items()
    )
    risk = max(0, min(100, risk))
    if risk < 35:
        code, level, loss = "STEADY_GUARDIAN", "conservative", 8
    elif risk < 65:
        code, level, loss = "BALANCED_NAVIGATOR", "moderate", 15
    else:
        code, level, loss = "LONG_HORIZON_BUILDER", "growth", 25
    title = (
        "理财启蒙学习者"
        if objective.get("age_range") == "minor"
        else ARCHETYPE_TITLES[code]
    )
    dimensions = {
        "risk_capacity": risk,
        "liquidity_resilience": min(100, int(objective.get("emergency_fund_months", 0)) * 8),
        "experience": {"none": 15, "beginner": 35, "intermediate": 65, "advanced": 90}.get(objective.get("investment_experience"), 40),
    }
    dimensions.update({key: round(float(value) * 100) for key, value in conversation_scores.items() if isinstance(value, (float, int))})
    low_confidence = sorted(
        {
            *skipped_dimensions,
            *(dimension for dimension in PROFILE_DIMENSIONS if dimension not in conversation_scores),
            *(dimension for dimension in PROFILE_DIMENSIONS if dimension not in profile_evidence),
            *(dimension for dimension, confidence in conversation_scores.items() if float(confidence) < 0.6),
        }
    )
    return ProfileAssessment(
        archetype_code=code,
        archetype_title=title,
        risk_level=level,
        loss_tolerance_percent=loss,
        dimension_scores=dimensions,
        summary=report_summary(objective, loss, low_confidence),
    )


def rank_directions(
    assessment: ProfileAssessment,
    objective: dict,
    education_only: bool,
    profile_evidence: dict | None = None,
) -> list[dict]:
    risk = assessment.dimension_scores["risk_capacity"]
    long_horizon = objective.get("fund_horizon") == "5_plus_years"
    evidence = profile_evidence or {}
    risk_tolerance = float(evidence.get("risk_tolerance", 0.0))
    liquidity_need = float(evidence.get("liquidity_need", 0.0))
    investment_goal = float(evidence.get("investment_goal", 0.0))
    loss_behavior = float(evidence.get("loss_behavior", 0.0))
    knowledge = float(evidence.get("investment_knowledge", 0.0))
    income_stability = float(evidence.get("income_stability", 0.0))
    scores = {
        "cash_fixed_income": 100 - risk * 0.5 + liquidity_need * 18 - investment_goal * 8 - income_stability * 5,
        "public_funds": 58 + risk * 0.25 - liquidity_need * 4 + investment_goal * 7 - knowledge * 3,
        "equities": 20 + risk * 0.75 - liquidity_need * 15 + investment_goal * 16 + knowledge * 10 + income_stability * 10 + risk_tolerance * 8 + loss_behavior * 8,
        "alternatives": 30 + risk * 0.35 - liquidity_need * 10 + knowledge * 12 + income_stability * 5,
        "long_term_insurance": 65 - risk * 0.2 - liquidity_need * 12 + income_stability * 7 + (10 if long_horizon else 0),
    }
    ordered = sorted(DIRECTIONS, key=lambda item: (-scores[item], DIRECTIONS.index(item)))
    horizon, experience, loss_reaction, reserve_months = objective_text(objective)
    adult_reasons = {
        "cash_fixed_income": (
            f"你已有约{reserve_months}个月应急资金，现金固收方向可继续承担短期备用和降低波动的作用；"
            "其价格和利率仍可能变化，不保证收益。"
        ),
        "public_funds": (
            f"你具备{experience}，公募基金可通过分散持仓降低单一标的研究压力，并与{horizon}的资金计划配合；"
            "基金净值仍会波动，不保证收益。"
        ),
        "equities": (
            f"你的资金计划为{horizon}，面对亏损倾向{loss_reaction}，规则采用约{assessment.loss_tolerance_percent}%的阶段性亏损承受阈值；"
            "股票方向可能出现更大回撤，应控制比例并分批投入，不保证收益。"
        ),
        "alternatives": (
            f"你具备{experience}，另类配置可用于理解与传统市场不同的风险来源，但流动性和估值透明度通常更弱；"
            "只适合作为有限补充，不保证收益。"
        ),
        "long_term_insurance": (
            f"你的资金计划为{horizon}，长期储蓄保险可用于学习保障与长期现金流安排，但锁定期较长、提前退出可能有损失；"
            "合同利益以条款为准，不保证收益。"
        ),
    }
    minor_reasons = {
        "cash_fixed_income": "未成年阶段仅用于金融教育，不可执行投资建议；可先学习现金管理、存款与固收风险，不保证收益。",
        "public_funds": "未成年阶段仅用于金融教育，不可执行投资建议；可先理解公募基金的分散机制、费用与净值波动，不保证收益。",
        "equities": "未成年阶段仅用于金融教育，不可执行投资建议；可先认识股票所有权、价格波动和本金亏损风险，不保证收益。",
        "alternatives": "未成年阶段仅用于金融教育，不可执行投资建议；可先了解另类资产的流动性、估值和信息透明度风险，不保证收益。",
        "long_term_insurance": "未成年阶段仅用于金融教育，不可执行投资建议；可先学习长期保险的保障责任、锁定期和退保损失，不保证收益。",
    }
    results = []
    for rank, direction in enumerate(ordered, start=1):
        reason = minor_reasons[direction] if education_only else adult_reasons[direction]
        results.append(
            {
                "direction": direction,
                "score": round(max(0, min(100, scores[direction])), 2),
                "rank": rank,
                "reason": reason,
                "actionable": not education_only,
            }
        )
    return results


STYLE_PROFILES = {
    "market_growth": {
        "style_logic": "市场增长型",
        "style_name": "长期市场参与者",
        "style_summary": "不猜谁会赢，长期持有整个市场，分享经济增长",
        "master_name": "约翰·博格",
        "master_name_en": "John Bogle",
    },
    "value_return": {
        "style_logic": "价值回归型",
        "style_name": "价值耐心寻找者",
        "style_summary": "寻找价格低于真实价值的好资产，耐心等待市场重新认识它",
        "master_name": "沃伦·巴菲特",
        "master_name_en": "Warren Buffett",
    },
    "growth_discovery": {
        "style_logic": "成长发现型",
        "style_name": "成长机会发现者",
        "style_summary": "寻找未来可能快速成长、但尚未被充分发现的企业",
        "master_name": "彼得·林奇",
        "master_name_en": "Peter Lynch",
    },
    "multi_asset": {
        "style_logic": "多资产配置型",
        "style_name": "多资产平衡者",
        "style_summary": "不把希望押在一种资产上，用不同资产应对不同环境",
        "master_name": "瑞·达利欧",
        "master_name_en": "Ray Dalio",
    },
    "trend_discipline": {
        "style_logic": "趋势交易型",
        "style_name": "趋势纪律执行者",
        "style_summary": "根据价格趋势和规则行动，并严格控制亏损",
        "master_name": "埃德·塞科塔",
        "master_name_en": "Ed Seykota",
    },
}

# 同分兜底：越靠前优先级越高（偏向更稳健/简单的类别）
STYLE_PRIORITY = ("market_growth", "value_return", "multi_asset", "growth_discovery", "trend_discipline")

STYLE_REASON_TEMPLATES = {
    "market_growth": "你的资金计划为{horizon}、亏损时倾向{loss}，这与博格主张的长期持有整个市场、少折腾的理念一致。",
    "value_return": "你的资金计划为{horizon}、亏损时倾向{loss}，这与巴菲特强调的价值判断与情绪纪律一致。",
    "growth_discovery": "你的资金计划为{horizon}、亏损时倾向{loss}，这与林奇寻找被低估成长机会的做法一致。",
    "multi_asset": "你的资金计划为{horizon}、亏损时倾向{loss}，这与达利欧用多资产分散应对不同环境的思路一致。",
    "trend_discipline": "你的资金计划为{horizon}、亏损时倾向{loss}，这与塞科塔顺势而为并严格止损的纪律一致。",
}
EDUCATION_STYLE_REASON = "作为学习标杆，博格倡导的低成本指数与长期定投，适合先建立稳健的投资常识。"


@dataclass(frozen=True)
class StyleMatch:
    style_code: str
    style_logic: str
    style_name: str
    style_summary: str
    master_name: str
    master_name_en: str
    match_reason: str


def _build_style_match(code: str, objective: dict, education_only: bool) -> StyleMatch:
    meta = STYLE_PROFILES[code]
    if education_only:
        reason = EDUCATION_STYLE_REASON
    else:
        horizon, _experience, loss_reaction, _reserve = objective_text(objective)
        reason = STYLE_REASON_TEMPLATES[code].format(horizon=horizon, loss=loss_reaction)
    return StyleMatch(style_code=code, match_reason=reason, **meta)


def match_style(
    objective: dict,
    risk_level: str,
    risk_capacity: float,
    profile_evidence: dict | None,
    education_only: bool,
) -> StyleMatch:
    if education_only:
        return _build_style_match("market_growth", objective, education_only=True)
    experience = objective.get("investment_experience")
    horizon = objective.get("fund_horizon")
    loss_reaction = objective.get("loss_reaction")
    reserve_months = max(0, int(objective.get("emergency_fund_months", 0) or 0))
    evidence = profile_evidence or {}
    knowledge = float(evidence.get("investment_knowledge", 0.0))
    goal = float(evidence.get("investment_goal", 0.0))
    liquidity = float(evidence.get("liquidity_need", 0.0))
    rc = float(risk_capacity or 0)
    scores = {
        "market_growth": (
            {"none": 30, "beginner": 22, "intermediate": 6, "advanced": 0}.get(experience, 0)
            + {"5_plus_years": 18, "3_5_years": 10, "1_3_years": 2, "under_1_year": -8}.get(horizon, 0)
            + {"hold": 16, "reduce": 6, "buy_more": 2, "sell_all": -6}.get(loss_reaction, 0)
            + (1 - knowledge) * 10
        ),
        "value_return": (
            {"intermediate": 22, "advanced": 16, "beginner": 6, "none": 0}.get(experience, 0)
            + {"5_plus_years": 18, "3_5_years": 12, "1_3_years": 2, "under_1_year": -10}.get(horizon, 0)
            + {"buy_more": 20, "hold": 12, "reduce": 2, "sell_all": -8}.get(loss_reaction, 0)
            + {"moderate": 6, "growth": 4, "conservative": 2}.get(risk_level, 0)
        ),
        "growth_discovery": (
            {"growth": 20, "moderate": 6, "conservative": -6}.get(risk_level, 0)
            + (rc / 100) * 15
            + {"buy_more": 18, "hold": 6}.get(loss_reaction, 0)
            + {"advanced": 14, "intermediate": 10, "beginner": 2}.get(experience, 0)
            + goal * 12
        ),
        "multi_asset": (
            {"reduce": 22, "hold": 6, "sell_all": 2}.get(loss_reaction, 0)
            + liquidity * 16
            + {"moderate": 12, "conservative": 6, "growth": 2}.get(risk_level, 0)
            + (6 if reserve_months >= 6 else 0)
        ),
        "trend_discipline": (
            {"advanced": 26, "intermediate": 8}.get(experience, 0)
            + (rc / 100) * 16
            + {"under_1_year": 18, "1_3_years": 10, "3_5_years": 0, "5_plus_years": -8}.get(horizon, 0)
            + {"sell_all": 14, "reduce": 12}.get(loss_reaction, 0)
            + knowledge * 10
        ),
    }
    best = max(STYLE_PRIORITY, key=lambda code: (scores[code], -STYLE_PRIORITY.index(code)))
    return _build_style_match(best, objective, education_only=False)
