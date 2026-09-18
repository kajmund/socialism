"""Existing installations receive the fix without replacing custom prompts."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa

from app.services.prompt_catalog import PROMPT_FIELDS


def test_focus_prompt_migration_preserves_customizations(monkeypatch):
    path = Path(__file__).parents[1] / 'alembic/versions/104_document_knowledge_focus.py'
    spec = importlib.util.spec_from_file_location('focus_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    defaults = next(p['defaults'] for p in PROMPT_FIELDS if p['key'] == migration._KEY)
    assert defaults == migration._NEW
    engine = sa.create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(sa.text('CREATE TABLE prompt_fields (key TEXT, default_sv TEXT, default_en TEXT, default_nb TEXT)'))
        conn.execute(sa.text('INSERT INTO prompt_fields VALUES (:key, :sv, :en, :nb)'),
                     {'key': migration._KEY, **migration._OLD})
        conn.execute(sa.text('INSERT INTO prompt_fields VALUES (:key, :sv, :en, :nb)'),
                     {'key': migration._KEY, 'sv': 'custom', 'en': 'custom', 'nb': 'custom'})
        monkeypatch.setattr(migration.op, 'get_bind', lambda: conn)
        migration.upgrade()
        migration.upgrade()
        rows = conn.execute(sa.text('SELECT default_sv, default_en, default_nb FROM prompt_fields')).all()
        assert rows[0] == tuple(defaults[lang] for lang in ('sv', 'en', 'nb'))
        assert rows[1] == ('custom', 'custom', 'custom')
        migration.downgrade()
        rows = conn.execute(sa.text('SELECT default_sv, default_en, default_nb FROM prompt_fields')).all()
        assert rows[0] == tuple(migration._OLD[lang] for lang in ('sv', 'en', 'nb'))
        assert rows[1] == ('custom', 'custom', 'custom')
