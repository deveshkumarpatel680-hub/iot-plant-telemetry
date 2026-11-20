from flask import Flask, jsonify, render_template, request
from db import Database

VALID_REMINDER_STATUSES = {"PENDING", "COMPLETED", "DISMISSED"}


def is_valid_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def create_app(test_config=None):
    app = Flask(__name__)

    if test_config:
        db = Database(
            use_mysql=False,
            sqlite_path=test_config.get("SQLITE_PATH", ":memory:"),
        )
    else:
        db = Database()

    db.init_sqlite_schema()
    app.db = db

    @app.route("/", methods=["GET"])
    def index():
        return render_template("index.html")

    @app.route("/api/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "backend": "mysql" if db.use_mysql else "sqlite"}), 200

    @app.route("/api/plants", methods=["GET"])
    def list_plants():
        # Two CTEs avoid cartesian row multiplication between readings and reminders
        query = """
            WITH reading_stats AS (
                SELECT
                    plant_id,
                    COUNT(*) AS total_readings,
                    ROUND(AVG(soil_moisture), 2) AS avg_moisture,
                    MAX(recorded_at) AS last_reading_at
                FROM sensor_readings
                GROUP BY plant_id
            ),
            alert_stats AS (
                SELECT
                    plant_id,
                    COUNT(*) AS pending_alerts
                FROM care_reminders
                WHERE status = 'PENDING'
                GROUP BY plant_id
            )
            SELECT
                p.id,
                p.name,
                p.species,
                p.moisture_threshold,
                COALESCE(rs.total_readings, 0) AS total_readings,
                rs.avg_moisture,
                rs.last_reading_at,
                COALESCE(a.pending_alerts, 0) AS pending_alerts
            FROM plants p
            LEFT JOIN reading_stats rs ON p.id = rs.plant_id
            LEFT JOIN alert_stats a ON p.id = a.plant_id
            ORDER BY p.id DESC
        """
        rows = db.fetch_all(query)
        for row in rows:
            row["moisture_threshold"] = float(row["moisture_threshold"])
            if row["avg_moisture"] is not None:
                row["avg_moisture"] = float(row["avg_moisture"])
        return jsonify({"plants": rows}), 200

    @app.route("/api/plants", methods=["POST"])
    def create_plant():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be valid JSON."}), 400

        name = str(data.get("name", "")).strip()
        species = str(data.get("species", "")).strip()
        threshold = data.get("moisture_threshold", 35.0)

        if not name or not species:
            return jsonify({"error": "Both 'name' and 'species' are required."}), 400
        if not is_valid_number(threshold) or not (0 <= threshold <= 100):
            return jsonify({"error": "'moisture_threshold' must be a number between 0 and 100."}), 400

        plant_id, _ = db.execute(
            "INSERT INTO plants (name, species, moisture_threshold) VALUES (%s, %s, %s)",
            (name, species, float(threshold)),
        )
        return jsonify(
            {
                "id": plant_id,
                "name": name,
                "species": species,
                "moisture_threshold": float(threshold),
            }
        ), 201

    @app.route("/api/readings", methods=["POST"])
    def ingest_reading():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be valid JSON."}), 400

        plant_id = data.get("plant_id")
        soil_moisture = data.get("soil_moisture")
        ambient_humidity = data.get("ambient_humidity")
        temperature_c = data.get("temperature_c")

        if not isinstance(plant_id, int) or isinstance(plant_id, bool):
            return jsonify({"error": "'plant_id' must be a valid integer."}), 400
        if not is_valid_number(soil_moisture) or not (0 <= soil_moisture <= 100):
            return jsonify({"error": "'soil_moisture' must be between 0 and 100."}), 400
        if not is_valid_number(ambient_humidity) or not (0 <= ambient_humidity <= 100):
            return jsonify({"error": "'ambient_humidity' must be between 0 and 100."}), 400
        if not is_valid_number(temperature_c) or not (-20 <= temperature_c <= 70):
            return jsonify({"error": "'temperature_c' must be between -20 and 70."}), 400

        plant = db.fetch_one(
            "SELECT id, name, moisture_threshold FROM plants WHERE id = %s",
            (plant_id,),
        )
        if not plant:
            return jsonify({"error": f"Plant with id {plant_id} not found."}), 404

        reading_id, _ = db.execute(
            """
            INSERT INTO sensor_readings (plant_id, soil_moisture, ambient_humidity, temperature_c)
            VALUES (%s, %s, %s, %s)
            """,
            (plant_id, float(soil_moisture), float(ambient_humidity), float(temperature_c)),
        )

        # Automated watering alert trigger with duplicate-open-alert guard
        alert_triggered = False
        reminder_id = None
        threshold = float(plant["moisture_threshold"])

        if float(soil_moisture) < threshold:
            existing = db.fetch_one(
                """
                SELECT id FROM care_reminders
                WHERE plant_id = %s AND alert_type = 'WATERING' AND status = 'PENDING'
                LIMIT 1
                """,
                (plant_id,),
            )
            if not existing:
                message = (
                    f"{plant['name']} moisture dropped to {soil_moisture:.1f}% "
                    f"(threshold: {threshold:.1f}%). Trigger watering."
                )
                reminder_id, _ = db.execute(
                    """
                    INSERT INTO care_reminders (plant_id, alert_type, message, status)
                    VALUES (%s, 'WATERING', %s, 'PENDING')
                    """,
                    (plant_id, message),
                )
                alert_triggered = True
            else:
                reminder_id = existing["id"]

        return jsonify(
            {
                "reading_id": reading_id,
                "plant_id": plant_id,
                "soil_moisture": float(soil_moisture),
                "alert_triggered": alert_triggered,
                "active_reminder_id": reminder_id,
            }
        ), 201

    @app.route("/api/plants/<int:plant_id>/summary", methods=["GET"])
    def plant_summary(plant_id):
        plant = db.fetch_one(
            "SELECT id, name, species, moisture_threshold FROM plants WHERE id = %s",
            (plant_id,),
        )
        if not plant:
            return jsonify({"error": f"Plant with id {plant_id} not found."}), 404

        stats = db.fetch_one(
            """
            SELECT
                COUNT(*) AS total_readings,
                ROUND(AVG(soil_moisture), 2) AS avg_moisture,
                MIN(soil_moisture) AS min_moisture,
                MAX(soil_moisture) AS max_moisture,
                ROUND(AVG(ambient_humidity), 2) AS avg_humidity,
                ROUND(AVG(temperature_c), 2) AS avg_temperature_c
            FROM sensor_readings
            WHERE plant_id = %s
            """,
            (plant_id,),
        )

        recent_readings = db.fetch_all(
            """
            SELECT id, soil_moisture, ambient_humidity, temperature_c, recorded_at
            FROM sensor_readings
            WHERE plant_id = %s
            ORDER BY id DESC
            LIMIT 10
            """,
            (plant_id,),
        )

        reminders = db.fetch_all(
            """
            SELECT id, alert_type, message, status, created_at
            FROM care_reminders
            WHERE plant_id = %s
            ORDER BY id DESC
            """,
            (plant_id,),
        )

        plant["moisture_threshold"] = float(plant["moisture_threshold"])
        for key in ("avg_moisture", "min_moisture", "max_moisture", "avg_humidity", "avg_temperature_c"):
            if stats[key] is not None:
                stats[key] = float(stats[key])

        return jsonify(
            {
                "plant": plant,
                "statistics": stats,
                "recent_readings": recent_readings,
                "reminders": reminders,
            }
        ), 200

    @app.route("/api/reminders/<int:reminder_id>", methods=["PUT"])
    def update_reminder(reminder_id):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be valid JSON."}), 400

        status = str(data.get("status", "")).upper().strip()
        if status not in VALID_REMINDER_STATUSES:
            return jsonify(
                {"error": f"Invalid status. Must be one of: {sorted(VALID_REMINDER_STATUSES)}"}
            ), 400

        _, rowcount = db.execute(
            "UPDATE care_reminders SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (status, reminder_id),
        )
        if rowcount == 0:
            return jsonify({"error": f"Reminder with id {reminder_id} not found."}), 404

        return jsonify({"id": reminder_id, "status": status}), 200

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)