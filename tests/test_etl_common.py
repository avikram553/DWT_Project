import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_sha256_file(tmp_path):
    from etl.common import sha256_file
    f = tmp_path / "test.txt"
    f.write_bytes(b"hello")
    result = sha256_file(f)
    assert len(result) == 64
    assert result == sha256_file(f)  # deterministic


def test_start_import_run():
    from etl.common import start_import_run
    db = MagicMock()
    # Should query sources by name, insert import_run, return id
    mock_source = MagicMock()
    mock_source.id = 1
    db.execute.return_value.scalar_one.return_value = mock_source.id

    run_id = start_import_run(db, "regionalatlas", "http://example.com/file.zip")
    db.execute.assert_called()
    db.commit.assert_called()
    assert isinstance(run_id, int)


def test_finish_import_run():
    from etl.common import finish_import_run
    db = MagicMock()
    finish_import_run(db, 42, status="success", rows_inserted=100, rows_updated=5, file_hash="abc123")
    db.execute.assert_called()
    db.commit.assert_called()
