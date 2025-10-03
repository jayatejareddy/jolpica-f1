import json
from pathlib import Path

import pytest

from jolpica.formula_one import models as f1
from jolpica.formula_one.importer.deserialisers import DeserialisationResult
from jolpica.formula_one.importer.importer import JSONModelImporter


@pytest.fixture
def importer() -> JSONModelImporter:
    return JSONModelImporter()


def test_deserialise_all_success(monkeypatch, importer):
    data = [
        {"object_type": "RoundEntry", "data": "round_entry_data"},
        {"object_type": "SessionEntry", "data": "session_entry_data"},
    ]

    def mock_get_deserialiser(object_type):
        class MockDeserialiser:
            def deserialise(self, data):
                return DeserialisationResult(success=True, data=data, instances={object_type: [data]})

        return MockDeserialiser()

    monkeypatch.setattr(importer.factory, "get_deserialiser", mock_get_deserialiser)

    result = importer.deserialise_all(data)

    assert result.success
    assert len(result.instances) == 2
    assert result.errors == []


def test_deserialise_all_with_errors(monkeypatch, importer):
    data = [
        {"object_type": "RoundEntry", "data": "round_entry_data"},
        {"object_type": "InvalidType", "data": "invalid_data"},
    ]

    def mock_get_deserialiser(object_type):
        class MockDeserialiser:
            def deserialise(self, data):
                if object_type == "InvalidType":
                    return DeserialisationResult(success=False, data=data, errors="Invalid object type")
                return DeserialisationResult(success=True, data=data, instances={object_type: [data]})

        return MockDeserialiser()

    monkeypatch.setattr(importer.factory, "get_deserialiser", mock_get_deserialiser)

    result = importer.deserialise_all(data)

    assert not result.success
    assert len(result.instances) == 1
    assert len(result.errors) == 1
    assert result.errors[0]["type"] == "InvalidType"
    assert result.errors[0]["message"] == "Invalid object type"


def test_deserialise_all_with_mixed_success(monkeypatch, importer):
    data = [
        {"object_type": "RoundEntry", "data": "round_entry_data"},
        {"object_type": "InvalidType", "data": "invalid_data"},
        {"object_type": "SessionEntry", "data": "session_entry_data"},
    ]

    def mock_get_deserialiser(object_type):
        class MockDeserialiser:
            def deserialise(self, data):
                if object_type == "InvalidType":
                    return DeserialisationResult(success=False, data=data, errors="Invalid object type")
                return DeserialisationResult(success=True, data=data, instances={object_type: [data]})

        return MockDeserialiser()

    monkeypatch.setattr(importer.factory, "get_deserialiser", mock_get_deserialiser)

    result = importer.deserialise_all(data)

    assert not result.success
    assert len(result.instances) == 2
    assert len(result.errors) == 1
    assert result.errors[0]["index"] == 1
    assert result.errors[0]["type"] == "InvalidType"
    assert result.errors[0]["message"] == "Invalid object type"


def test_deserialise_all_prioritisation(monkeypatch, importer):
    data = [
        {"object_type": "SessionEntry", "data": "session_entry_data"},
        {"object_type": "RoundEntry", "data": "round_entry_data"},
    ]

    deserialisation_order = []

    def mock_get_deserialiser(object_type):
        class MockDeserialiser:
            def deserialise(self, data):
                deserialisation_order.append(object_type)
                return DeserialisationResult(success=True, data=data, instances={object_type: [data]})

        return MockDeserialiser()

    monkeypatch.setattr(importer.factory, "get_deserialiser", mock_get_deserialiser)

    result = importer.deserialise_all(data)

    assert result.success
    assert len(result.instances) == 2
    assert result.errors == []
    assert deserialisation_order == ["RoundEntry", "SessionEntry"]


@pytest.mark.django_db
def test_deserialise_monaco_data(importer: JSONModelImporter):
    with open(Path("jolpica/formula_one/tests/fixtures/2024_08_monaco.json")) as f:
        data = json.load(f)

    result = importer.deserialise_all(data)

    assert result.errors == []
    assert result.success

    for model_import, instances in result.instances.items():
        if model_import.model_class is f1.PitStop:
            for ins in instances:
                assert ins.lap is not None

    assert f1.managed_views.DriverChampionship.objects.filter(year=2024).count() == 0
    assert f1.PitStop.objects.filter(lap__isnull=True).count() == 0
    importer.save_deserialisation_result_to_db(result)
    assert f1.managed_views.DriverChampionship.objects.filter(year=2024).count() > 0
    assert f1.PitStop.objects.filter(lap__isnull=True).count() == 0


@pytest.mark.django_db
def test_import_new_pit_stops(importer: JSONModelImporter):
    season = f1.Season.objects.create(id=1000, year=2125, championship_system_id=1)
    round = f1.Round.objects.create(season=season, id=999999, number=1, circuit_id=1)
    f1.Session.objects.create(id=99999, round=round, number=7, type="R")
    with open(Path("jolpica/formula_one/tests/fixtures/2025_01_pit_stops.json")) as f:
        data = json.load(f)

    result = importer.deserialise_all(data)

    assert result.errors == []
    assert result.success

    for model_import, instances in result.instances.items():
        if model_import.model_class is f1.PitStop:
            for ins in instances:
                assert ins.lap is not None

    results = importer.save_deserialisation_result_to_db(result)
    assert results["models"]["PitStop"]["updated_count"] == 0
    assert results["models"]["PitStop"]["created_count"] == 82
    assert len(set(results["models"]["PitStop"]["created"])) == 82
