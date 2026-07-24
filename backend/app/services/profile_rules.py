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
