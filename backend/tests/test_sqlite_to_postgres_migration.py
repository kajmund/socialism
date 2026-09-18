import pytest
from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table, create_engine, select

from scripts.migrate_sqlite_to_postgres import copy_database


def test_copy_database_preserves_rows_and_relationships() -> None:
    metadata = MetaData()
    parents = Table(
        "parents",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String, nullable=False),
    )
    children = Table(
        "children",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("parent_id", ForeignKey("parents.id"), nullable=False),
        Column("name", String, nullable=False),
    )
    source = create_engine("sqlite://")
    target = create_engine("sqlite://")
    metadata.create_all(source)
    metadata.create_all(target)
    with source.begin() as connection:
        connection.execute(parents.insert(), [{"id": 4, "name": "A"}])
        connection.execute(
            children.insert(),
            [
                {"id": 8, "parent_id": 4, "name": "B"},
                {"id": 9, "parent_id": 4, "name": "C"},
            ],
        )

    counts = copy_database(
        source,
        target,
        metadata=metadata,
        verify_revisions=False,
    )

    assert counts == {"parents": 1, "children": 2}
    with target.connect() as connection:
        assert connection.execute(select(parents)).all() == [(4, "A")]
        assert connection.execute(select(children).order_by(children.c.id)).all() == [
            (8, 4, "B"),
            (9, 4, "C"),
        ]


def test_copy_database_requires_explicit_replace_for_seeded_target() -> None:
    metadata = MetaData()
    items = Table(
        "items",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String, nullable=False),
    )
    source = create_engine("sqlite://")
    target = create_engine("sqlite://")
    metadata.create_all(source)
    metadata.create_all(target)
    with source.begin() as connection:
        connection.execute(items.insert(), {"id": 1, "name": "source"})
    with target.begin() as connection:
        connection.execute(items.insert(), {"id": 99, "name": "migration seed"})

    with pytest.raises(RuntimeError, match="--replace-target"):
        copy_database(source, target, metadata=metadata, verify_revisions=False)

    counts = copy_database(
        source,
        target,
        metadata=metadata,
        verify_revisions=False,
        replace_target=True,
    )

    assert counts == {"items": 1}
    with target.connect() as connection:
        assert connection.execute(select(items)).all() == [(1, "source")]
