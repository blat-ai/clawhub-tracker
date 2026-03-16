"""Shared fixtures for unit tests."""

import pytest

from app.storage import get_connection, init_schema


@pytest.fixture
def db():
    """In-memory DuckDB connection with schema initialized."""
    conn = get_connection(":memory:")
    init_schema(conn)
    yield conn
    conn.close()
