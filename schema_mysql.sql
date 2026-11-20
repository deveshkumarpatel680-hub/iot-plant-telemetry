CREATE DATABASE IF NOT EXISTS plant_telemetry;
USE plant_telemetry;

CREATE TABLE IF NOT EXISTS plants (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    species VARCHAR(100) NOT NULL,
    moisture_threshold DECIMAL(5,2) NOT NULL DEFAULT 35.00,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_threshold CHECK (moisture_threshold >= 0 AND moisture_threshold <= 100)
);

CREATE TABLE IF NOT EXISTS sensor_readings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    plant_id INT NOT NULL,
    soil_moisture DECIMAL(5,2) NOT NULL,
    ambient_humidity DECIMAL(5,2) NOT NULL,
    temperature_c DECIMAL(5,2) NOT NULL,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_reading_plant
        FOREIGN KEY (plant_id) REFERENCES plants(id) ON DELETE CASCADE,
    INDEX idx_readings_plant_time (plant_id, recorded_at)
);

CREATE TABLE IF NOT EXISTS care_reminders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    plant_id INT NOT NULL,
    alert_type VARCHAR(50) NOT NULL DEFAULT 'WATERING',
    message VARCHAR(255) NOT NULL,
    status ENUM('PENDING', 'COMPLETED', 'DISMISSED') NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_reminder_plant
        FOREIGN KEY (plant_id) REFERENCES plants(id) ON DELETE CASCADE,
    INDEX idx_reminders_plant_status (plant_id, status)
);