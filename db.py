import os
import sqlite3
from contextlib import contextmanager


class Database:
    def __init__(self, use_mysql=None, sqlite_path="plant_telemetry.db"):
        if use_mysql is None:
            use_mysql = os.getenv("USE_MYSQL", "false").lower() == "true"
        self.use_mysql = use_mysql
        self.sqlite_path = sqlite_path

    @contextmanager
    def connect(self):
        if self.use_mysql:
            import mysql.connector

            conn = mysql.connector.connect(
                host=os.getenv("MYSQL_HOST", "localhost"),
                user=os.getenv("MYSQL_USER", "root"),
                password=os.getenv("MYSQL_PASSWORD", ""),
                database=os.getenv("MYSQL_DB", "plant_telemetry"),
            )
            cursor = conn.cursor(dictionary=True)
            try:
                yield conn, cursor
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()
                conn.close()
        else:
            conn = sqlite3.connect(self.sqlite_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            cursor = conn.cursor()
            try:
                yield conn, cursor
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()
                conn.close()

    def _adapt_sql(self, query):
        return query if self.use_mysql else query.replace("%s", "?")

    def execute(self, query, params=()):
        adapted = self._adapt_sql(query)
        with self.connect() as (_, cursor):
            cursor.execute(adapted, params)
            return cursor.lastrowid, cursor.rowcount

    def fetch_one(self, query, params=()):
        adapted = self._adapt_sql(query)
        with self.connect() as (_, cursor):
            cursor.execute(adapted, params)
            row = cursor.fetchone()
            return dict(row) if row else None

    def fetch_all(self, query, params=()):
        adapted = self._adapt_sql(query)
        with self.connect() as (_, cursor):
            cursor.execute(adapted, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def init_sqlite_schema(self):
        if self.use_mysql:
            return
        with self.connect() as (_, cursor):
            cursor.executescript(
                """
                CREATE TABLE IF NOT EXISTS plants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    species TEXT NOT NULL,
                    moisture_threshold REAL NOT NULL DEFAULT 35.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS sensor_readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plant_id INTEGER NOT NULL,
                    soil_moisture REAL NOT NULL,
                    ambient_humidity REAL NOT NULL,
                    temperature_c REAL NOT NULL,
                    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (plant_id) REFERENCES plants(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS care_reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plant_id INTEGER NOT NULL,
                    alert_type TEXT NOT NULL DEFAULT 'WATERING',
                    message TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (plant_id) REFERENCES plants(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_readings_plant_time
                    ON sensor_readings(plant_id, recorded_at);
                CREATE INDEX IF NOT EXISTS idx_reminders_plant_status
                    ON care_reminders(plant_id, status);
                """
            )