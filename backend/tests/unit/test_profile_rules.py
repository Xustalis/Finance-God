import re

from app.services.profile_rules import assess_profile, rank_directions


OBJECTIVE = {
    "loss_reaction": "hold",
    "fund_horizon": "5_plus_years",
    "emergency_fund_months": 8,
    "investment_experience": "intermediate",
}


def test_confirmed_ai_evidence_changes_deterministic_risk_score() -> None:
    cautious = assess_profile(OBJECTIVE, {"risk_tolerance": 0.9}, {"risk_tolerance": -1.0}, [])
    adventurous = assess_profile(OBJECTIVE, {"risk_tolerance": 0.9}, {"risk_tolerance": 1.0}, [])

    assert cautious.dimension_scores["risk_capacity"] < adventurous.dimension_scores["risk_capacity"]


def test_low_confidence_lists_missing_skipped_and_weak_dimensions() -> None:
    assessment = assess_profile(
        OBJECTIVE,
        {"risk_tolerance": 0.4, "liquidity_need": 0.9},
        {"risk_tolerance": 0.2, "liquidity_need": 0.1},
        ["income_stability"],
    )

    low_confidence = assessment.summary["low_confidence"]
    assert "risk_tolerance" in low_confidence
    assert "income_stability" in low_confidence
    assert "investment_goal" in low_confidence


def test_all_six_dimensions_have_stable_risk_contributions() -> None:
    dimensions = (
        "risk_tolerance",
        "liquidity_need",
        "investment_goal",
        "loss_behavior",
        "investment_knowledge",
        "income_stability",
    )
    for dimension in dimensions:
        negative = assess_profile(OBJECTIVE, {dimension: 0.9}, {dimension: -1.0}, [])
        positive = assess_profile(OBJECTIVE, {dimension: 0.9}, {dimension: 1.0}, [])
        assert negative.dimension_scores["risk_capacity"] != positive.dimension_scores["risk_capacity"], dimension


def test_opposite_multi_dimension_evidence_can_change_direction_order() -> None:
    defensive_evidence = {
        "risk_tolerance": -1.0,
        "liquidity_need": 1.0,
        "investment_goal": -1.0,
        "loss_behavior": -1.0,
        "investment_knowledge": -1.0,
        "income_stability": -1.0,
    }
    growth_evidence = {dimension: -value for dimension, value in defensive_evidence.items()}
    defensive = assess_profile(OBJECTIVE, {key: 0.9 for key in defensive_evidence}, defensive_evidence, [])
    growth = assess_profile(OBJECTIVE, {key: 0.9 for key in growth_evidence}, growth_evidence, [])

    defensive_order = [item["direction"] for item in rank_directions(defensive, OBJECTIVE, False, defensive_evidence)]
    growth_order = [item["direction"] for item in rank_directions(growth, OBJECTIVE, False, growth_evidence)]

    assert defensive_order != growth_order
    assert defensive_order.index("cash_fixed_income") < defensive_order.index("equities")
    assert growth_order.index("equities") < growth_order.index("cash_fixed_income")


def test_user_report_is_natural_chinese_and_preserves_objective_facts() -> None:
    assessment = assess_profile(OBJECTIVE, {}, {}, [])
    user_text = " ".join(
        [
            assessment.archetype_title,
            *assessment.summary["traits"],
            assessment.summary["risk_notice"],
            *assessment.summary["reasoning"],
        ]
    )

    assert re.search(r"[\u4e00-\u9fff]", assessment.archetype_title)
    assert 1 <= len(assessment.summary["traits"]) <= 5
    assert "5年以上" in user_text
    assert "8个月" in user_text
    assert "继续持有" in user_text
    assert "中等投资经验" in user_text
    assert f"{assessment.loss_tolerance_percent}%" in user_text
    assert "不保证" in assessment.summary["risk_notice"]
    for placeholder in (
        "Steady Guardian",
        "Balanced Navigator",
        "Long-Horizon Builder",
        "Plan-led",
        "Risk-aware",
        "fund_horizon",
        "emergency_fund_months",
    ):
        assert placeholder not in user_text


def test_direction_reasons_are_chinese_specific_and_stable() -> None:
    assessment = assess_profile(OBJECTIVE, {}, {}, [])
    first = rank_directions(assessment, OBJECTIVE, False, {})
    second = rank_directions(assessment, OBJECTIVE, False, {})
    reasons = {item["direction"]: item["reason"] for item in first}

    assert first == second
    assert len(set(reasons.values())) == 5
    assert "现金" in reasons["cash_fixed_income"] and "应急资金" in reasons["cash_fixed_income"]
    assert "分散" in reasons["public_funds"] and "中等投资经验" in reasons["public_funds"]
    assert "股票" in reasons["equities"] and "5年以上" in reasons["equities"]
    assert "另类" in reasons["alternatives"] and "流动性" in reasons["alternatives"]
    assert "保险" in reasons["long_term_insurance"] and "长期" in reasons["long_term_insurance"]
    for reason in reasons.values():
        assert re.search(r"[\u4e00-\u9fff]", reason)
        assert "不保证收益" in reason
        assert "moderate" not in reason
        assert "growth" not in reason
        assert "conservative" not in reason
        assert "fund_horizon" not in reason
        assert "稳赚" not in reason
        assert "必赚" not in reason


def test_minor_output_is_chinese_education_only_and_non_actionable() -> None:
    minor_objective = OBJECTIVE | {"age_range": "minor"}
    assessment = assess_profile(minor_objective, {}, {}, [])
    recommendations = rank_directions(assessment, minor_objective, True, {})

    assert assessment.archetype_title == "理财启蒙学习者"
    assert "未成年" in assessment.summary["risk_notice"]
    assert all(item["actionable"] is False for item in recommendations)
    assert len({item["reason"] for item in recommendations}) == 5
    for item in recommendations:
        assert "金融教育" in item["reason"]
        assert "不可执行" in item["reason"]
        assert re.search(r"[\u4e00-\u9fff]", item["reason"])
