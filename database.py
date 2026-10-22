"""Shared schema and environment-based database configuration."""
import os
from contextlib import contextmanager

import mysql.connector

SCHEMA = """
CREATE TABLE IF NOT EXISTS extracted_knowledge (
    id INT AUTO_INCREMENT PRIMARY KEY,
    category VARCHAR(255) NOT NULL,
    sentence TEXT NOT NULL,
    accuracy FLOAT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def connect_database():
    options = {}
    if os.environ.get("DB_SOCKET"):
        options["unix_socket"] = os.environ["DB_SOCKET"]
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "knowledge_app"),
        password=os.environ.get("DB_PASSWORD", ""),
        database=os.environ.get("DB_NAME", "uas_km"),
        charset="utf8mb4",
        connection_timeout=5,
        autocommit=False,
        **options,
    )


@contextmanager
def transaction(connection):
    cursor = connection.cursor()
    try:
        yield cursor
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
