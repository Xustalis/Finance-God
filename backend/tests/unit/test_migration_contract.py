from pathlib import Path


def test_initial_migration_uses_explicit_operations() -> None:
    migration = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20260723_0001_initial_schema.py"
    ).read_text()

    assert "op.create_table" in migration
    assert "op.create_index" in migration
    assert "metadata.create_all" not in migration
    assert "metadata.drop_all" not in migration
    ai_config_section, onboarding_section = migration.split('"ai_model_configs"', 1)[1].split('"onboarding_sessions"', 1)
    assert 'sa.Column("prompt_hash"' not in ai_config_section
    assert 'sa.Column("prompt_hash"' in onboarding_section
    assert 'sa.Column("prompt_content"' in onboarding_section


def test_current_question_uses_independent_followup_migration() -> None:
    versions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    initial = (versions / "20260723_0001_initial_schema.py").read_text()
    followup = (versions / "20260724_0002_current_question.py").read_text()

    assert 'sa.Column("current_question"' not in initial
    assert 'revision: str = "20260724_0002"' in followup
    assert 'down_revision: str | None = "20260723_0001"' in followup
    assert 'op.add_column("onboarding_sessions"' in followup
    assert 'sa.Column("current_question", sa.Text(), nullable=True)' in followup
    assert 'op.drop_column("onboarding_sessions", "current_question")' in followup
