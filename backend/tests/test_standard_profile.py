from types import SimpleNamespace
import sqlite3

import pytest

from app.services import model_registry
from app.db import bootstrap
from app.services.auto_tuning import service as tuning


def test_standard_profile_blocks_foundation_model_even_if_installed(monkeypatch):
    monkeypatch.setattr(model_registry, 'get_settings', lambda: SimpleNamespace(model_profile='standard'))
    monkeypatch.setattr(model_registry, '_module_available', lambda name: True)
    capabilities = model_registry.get_model_capabilities()
    timesfm = next(item for item in capabilities if item.id == 'timesfm')
    assert timesfm.availabilityStatus == 'unavailable'
    with pytest.raises(ValueError, match='TimesFM'):
        model_registry.create_model('timesfm')
    assert model_registry.create_model('naive').model_id == 'naive'


def test_preserved_startup_does_not_migrate_or_write_database(tmp_path, monkeypatch):
    database = tmp_path / 'forecast_lab.sqlite'
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE sentinel (value TEXT)')
        connection.execute("INSERT INTO sentinel VALUES ('keep me')")
    before = database.read_bytes()
    monkeypatch.setattr(bootstrap, 'get_settings', lambda: SimpleNamespace(data_dir=tmp_path, preserve_existing_data=True))
    bootstrap.bootstrap_database(None)
    assert database.read_bytes() == before


def test_preserved_startup_fails_closed_without_database(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, 'get_settings', lambda: SimpleNamespace(data_dir=tmp_path, preserve_existing_data=True))
    with pytest.raises(RuntimeError, match='existing database'):
        bootstrap.bootstrap_database(None)


def test_standard_tuning_uses_candidate_limits_not_wall_clock(monkeypatch):
    monkeypatch.setattr(tuning, 'get_settings', lambda: SimpleNamespace(model_profile='standard'))
    assert tuning.describe_tuning_profile('fast') == {'candidateLimit': 4, 'timeBudgetSeconds': 0.0}
    monkeypatch.setattr(tuning, 'get_settings', lambda: SimpleNamespace(model_profile='full'))
    assert tuning.describe_tuning_profile('fast')['timeBudgetSeconds'] == 3.0
