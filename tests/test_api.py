import pytest
from app import create_app


@pytest.fixture
def client(tmp_path):
    db_file = tmp_path / "test_telemetry.db"
    app = create_app({"SQLITE_PATH": str(db_file)})
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_create_and_list_plant(client):
    res = client.post(
        "/api/plants",
        json={"name": "Mint Pot", "species": "Mentha", "moisture_threshold": 40.0},
    )
    assert res.status_code == 201
    created = res.get_json()
    assert created["name"] == "Mint Pot"

    list_res = client.get("/api/plants")
    assert list_res.status_code == 200
    plants = list_res.get_json()["plants"]
    assert len(plants) == 1
    assert plants[0]["pending_alerts"] == 0


def test_create_plant_rejects_invalid_payload(client):
    res = client.post(
        "/api/plants",
        json={"name": "", "species": "Aloe", "moisture_threshold": 150},
    )
    assert res.status_code == 400


def test_low_moisture_triggers_single_non_duplicate_alert(client):
    plant_id = client.post(
        "/api/plants",
        json={"name": "Tulsi", "species": "Ocimum tenuiflorum", "moisture_threshold": 35},
    ).get_json()["id"]

    # First low reading triggers alert
    r1 = client.post(
        "/api/readings",
        json={"plant_id": plant_id, "soil_moisture": 22.5, "ambient_humidity": 50, "temperature_c": 28},
    )
    assert r1.status_code == 201
    body1 = r1.get_json()
    assert body1["alert_triggered"] is True
    assert body1["active_reminder_id"] is not None

    # Second consecutive low reading should NOT create a duplicate pending alert
    r2 = client.post(
        "/api/readings",
        json={"plant_id": plant_id, "soil_moisture": 20.0, "ambient_humidity": 48, "temperature_c": 29},
    )
    assert r2.status_code == 201
    body2 = r2.get_json()
    assert body2["alert_triggered"] is False
    assert body2["active_reminder_id"] == body1["active_reminder_id"]


def test_reading_rejects_out_of_range_and_boolean_values(client):
    plant_id = client.post(
        "/api/plants",
        json={"name": "Fern", "species": "Nephrolepis"},
    ).get_json()["id"]

    bad_payloads = [
        {"plant_id": plant_id, "soil_moisture": 120, "ambient_humidity": 50, "temperature_c": 25},
        {"plant_id": plant_id, "soil_moisture": True, "ambient_humidity": 50, "temperature_c": 25},
        {"plant_id": plant_id, "soil_moisture": 40, "ambient_humidity": 50, "temperature_c": 99},
    ]
    for payload in bad_payloads:
        res = client.post("/api/readings", json=payload)
        assert res.status_code == 400


def test_reading_for_unknown_plant_returns_404(client):
    res = client.post(
        "/api/readings",
        json={"plant_id": 999, "soil_moisture": 40, "ambient_humidity": 50, "temperature_c": 25},
    )
    assert res.status_code == 404


def test_update_reminder_status_and_validation(client):
    plant_id = client.post(
        "/api/plants",
        json={"name": "Cactus", "species": "Cactaceae", "moisture_threshold": 30},
    ).get_json()["id"]

    reminder_id = client.post(
        "/api/readings",
        json={"plant_id": plant_id, "soil_moisture": 10, "ambient_humidity": 30, "temperature_c": 32},
    ).get_json()["active_reminder_id"]

    # Reject invalid status
    bad_put = client.put(f"/api/reminders/{reminder_id}", json={"status": "UNKNOWN"})
    assert bad_put.status_code == 400

    # Mark completed
    ok_put = client.put(f"/api/reminders/{reminder_id}", json={"status": "COMPLETED"})
    assert ok_put.status_code == 200
    assert ok_put.get_json()["status"] == "COMPLETED"

    # Non-existent reminder returns 404
    missing_put = client.put("/api/reminders/9999", json={"status": "DISMISSED"})
    assert missing_put.status_code == 404


def test_plant_summary_sql_aggregations(client):
    plant_id = client.post(
        "/api/plants",
        json={"name": "Money Plant", "species": "Epipremnum aureum", "moisture_threshold": 35},
    ).get_json()["id"]

    client.post("/api/readings", json={"plant_id": plant_id, "soil_moisture": 40, "ambient_humidity": 60, "temperature_c": 24})
    client.post("/api/readings", json={"plant_id": plant_id, "soil_moisture": 60, "ambient_humidity": 70, "temperature_c": 26})

    res = client.get(f"/api/plants/{plant_id}/summary")
    assert res.status_code == 200
    stats = res.get_json()["statistics"]
    assert stats["total_readings"] == 2
    assert stats["avg_moisture"] == 50.0
    assert stats["min_moisture"] == 40.0
    assert stats["max_moisture"] == 60.0