"""Initialize the table in an existing database; never connect on import."""
from database import SCHEMA, connect_database, transaction


def main():
    connection = connect_database()
    try:
        with transaction(connection) as cursor:
            cursor.execute(SCHEMA)
        print("Table extracted_knowledge is ready.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
