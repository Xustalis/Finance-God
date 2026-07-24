"""question_bank 模块单元测试。"""

from __future__ import annotations

from app.schemas.onboarding import ProfileDimension
from app.services.question_bank import (
    EXCERPT_LIMIT,
    QUESTION_TEMPLATES,
    make_excerpt,
    render_template,
    select_question,
)

ALL_DIMENSIONS = [item.value for item in ProfileDimension]

INITIAL_RISK_QUESTION = "如果这笔资金出现约15%的阶段性亏损，你更可能继续持有、减少投入，还是全部卖出？"


def test_covers_all_dimensions() -> None:
    assert set(QUESTION_TEMPLATES) == set(ALL_DIMENSIONS)


def test_each_dimension_has_at_least_three_templates() -> None:
    for dimension in ALL_DIMENSIONS:
        assert len(QUESTION_TEMPLATES[dimension]) >= 3, dimension


def test_template_ids_globally_unique() -> None:
    ids = [t.template_id for templates in QUESTION_TEMPLATES.values() for t in templates]
    assert len(ids) == len(set(ids))


def test_template_fields_valid() -> None:
    for templates in QUESTION_TEMPLATES.values():
        for template in templates:
            assert template.level in {"initial", "retry", "deepened"}
            assert template.mode in {"scenario", "direct", "metaphor"}
            assert template.content.strip()


def test_initial_risk_question_preserved() -> None:
    contents = [t.content for t in QUESTION_TEMPLATES[ProfileDimension.RISK_TOLERANCE.value]]
    assert INITIAL_RISK_QUESTION in contents


def test_followup_returns_different_question() -> None:
    for dimension in ALL_DIMENSIONS:
        first = select_question(dimension, followup_count=0)
        second = select_question(dimension, followup_count=1, asked_questions=[first])
        assert first != second
        assert first and second


def test_all_asked_still_returns_nonempty() -> None:
    for dimension in ALL_DIMENSIONS:
        all_rendered = [render_template(t) for t in QUESTION_TEMPLATES[dimension]]
        result = select_question(dimension, followup_count=2, asked_questions=all_rendered)
        assert isinstance(result, str)
        assert result.strip()


def test_excerpt_formatting_no_placeholder_residue() -> None:
    excerpt = "我担心亏钱"
    for dimension in ALL_DIMENSIONS:
        for template in QUESTION_TEMPLATES[dimension]:
            with_excerpt = render_template(template, excerpt)
            without_excerpt = render_template(template, None)
            assert "{excerpt}" not in with_excerpt
            assert "{excerpt}" not in without_excerpt
            assert with_excerpt.strip() and without_excerpt.strip()
            if "{excerpt}" in template.content:
                assert excerpt in with_excerpt


def test_excerpt_truncated_to_limit() -> None:
    long_text = "这是一段非常非常长的用户回答内容，远远超过二十四个字符的截断上限，用于测试摘要截断逻辑。"
    excerpt = make_excerpt(long_text)
    assert len(excerpt) <= EXCERPT_LIMIT
    assert excerpt == long_text[:EXCERPT_LIMIT].rstrip()

    template = next(
        t
        for t in QUESTION_TEMPLATES[ProfileDimension.RISK_TOLERANCE.value]
        if "{excerpt}" in t.content
    )
    rendered = render_template(template, long_text)
    assert excerpt in rendered
    assert long_text not in rendered


def test_select_question_nonempty_for_all_followup_counts() -> None:
    for dimension in ALL_DIMENSIONS:
        for followup_count in (0, 1, 2):
            result = select_question(dimension, followup_count=followup_count)
            assert isinstance(result, str)
            assert result.strip()


def test_select_question_deterministic() -> None:
    for dimension in ALL_DIMENSIONS:
        a = select_question(dimension, followup_count=1, user_excerpt="想给孩子存教育金")
        b = select_question(dimension, followup_count=1, user_excerpt="想给孩子存教育金")
        assert a == b


def test_initial_prefers_initial_level() -> None:
    for dimension in ALL_DIMENSIONS:
        result = select_question(dimension, followup_count=0)
        initial_contents = {
            render_template(t) for t in QUESTION_TEMPLATES[dimension] if t.level == "initial"
        }
        assert result in initial_contents
