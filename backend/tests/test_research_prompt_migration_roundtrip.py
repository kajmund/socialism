"""Research prompt migrations must remove their overrides on rollback."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.database.models import PromptField, PromptOverride


@pytest.mark.parametrize('revision', [110, 114, 115, 116, 117, 118, 119, 120])
def test_prompt_migration_round_trip_preserves_unrelated_prompts(revision):
    path = next((Path(__file__).parents[1] / 'alembic/versions').glob(f'{revision}_*.py'))
    spec = importlib.util.spec_from_file_location(f'prompt_migration_{revision}', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    metadata = sa.MetaData()
    # Only foreign-key parent identities are needed; use the real prompt schemas.
    for name in ('kunder', 'llm_configurations'):
        sa.Table(name, metadata, sa.Column('id', sa.Integer, primary_key=True))
    fields = PromptField.__table__.to_metadata(metadata)
    overrides = PromptOverride.__table__.to_metadata(metadata)
    sa.Table('research_runtime_needs', metadata, sa.Column('id', sa.Integer, primary_key=True))
    engine = sa.create_engine('sqlite://')
    with engine.begin() as conn:
        conn.exec_driver_sql('PRAGMA foreign_keys=ON')
        metadata.create_all(conn)
        conn.execute(metadata.tables['kunder'].insert().values(id=1))
        unrelated_id = conn.execute(fields.insert().values(
            key='unrelated.test', modules=[], section='test', default_sv='unchanged'
        )).inserted_primary_key[0]
        conn.execute(overrides.insert().values(
            customer_id=1, prompt_field_id=unrelated_id, language='sv', text='keep me'
        ))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            for key in migration._NEW_KEYS:
                field_id = conn.scalar(sa.select(fields.c.id).where(fields.c.key == key))
                assert field_id is not None
                conn.execute(overrides.insert().values(
                    customer_id=1, prompt_field_id=field_id, language='sv', text='custom'
                ))
            migration.downgrade()
            assert conn.execute(sa.select(fields.c.key, fields.c.default_sv)).all() == [
                ('unrelated.test', 'unchanged')
            ]
            assert conn.scalars(sa.select(overrides.c.text)).all() == ['keep me']
            if revision == 114:
                assert [c['name'] for c in sa.inspect(conn).get_columns('research_runtime_needs')] == ['id']
            # A second upgrade must restore usable fields after rollback.
            migration.upgrade()
            assert set(conn.scalars(sa.select(fields.c.key))) == {'unrelated.test', *migration._NEW_KEYS}
    engine.dispose()
