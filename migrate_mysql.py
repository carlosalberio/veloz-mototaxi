"""Safely extend the existing XAMPP mototaxi tables for website accounts."""

import logging

import pymysql

from database import connect_database


TABLES = {
    "usuarios": "usuarios",
    "mototaxistas": "mototaxistas",
}

NEW_COLUMNS = {
    "usuarios": {
        "idade": "SMALLINT UNSIGNED NULL",
        "senha_hash": "VARCHAR(255) NULL",
    },
    "mototaxistas": {
        "idade": "SMALLINT UNSIGNED NULL",
        "senha_hash": "VARCHAR(255) NULL",
        "cpf": "VARCHAR(11) NULL",
        "cnh": "VARCHAR(11) NULL",
        "categoria_cnh": "VARCHAR(3) NULL",
        "validade_cnh": "DATE NULL",
        "moto": "VARCHAR(120) NULL",
        "placa": "VARCHAR(8) NULL",
    },
}


def migrate_table(connection, table, index_name):
    with connection.cursor() as cursor:
        cursor.execute("SHOW COLUMNS FROM `{}`".format(table))
        columns = {row["Field"] for row in cursor.fetchall()}
        cursor.execute("SHOW INDEX FROM `{}`".format(table))
        indexes = cursor.fetchall()
        has_unique_email = any(
            row["Column_name"] == "email"
            and row["Non_unique"] == 0
            and row["Seq_in_index"] == 1
            for row in indexes
        )
        if not has_unique_email:
            cursor.execute(
                "SELECT COUNT(*) AS duplicate_groups FROM ("
                "SELECT LOWER(`email`) FROM `{}` GROUP BY LOWER(`email`) "
                "HAVING COUNT(*) > 1) AS duplicates".format(table)
            )
            if cursor.fetchone()["duplicate_groups"]:
                raise RuntimeError(
                    "A tabela `{}` tem e-mails repetidos; corrija-os antes da migração.".format(
                        table
                    )
                )

        if "telefone:" in columns and "telefone" not in columns:
            cursor.execute(
                "ALTER TABLE `{}` CHANGE COLUMN `telefone:` `telefone` VARCHAR(32) NOT NULL".format(
                    table
                )
            )
            columns.remove("telefone:")
            columns.add("telefone")
        elif "telefone" not in columns:
            raise RuntimeError("A tabela `{}` não possui a coluna de telefone esperada.".format(table))
        else:
            cursor.execute(
                "ALTER TABLE `{}` MODIFY COLUMN `telefone` VARCHAR(32) NOT NULL".format(table)
            )

        cursor.execute(
            "ALTER TABLE `{}` MODIFY COLUMN `nome` VARCHAR(120) NOT NULL, "
            "MODIFY COLUMN `email` VARCHAR(254) NOT NULL".format(table)
        )

        for column, definition in NEW_COLUMNS[table].items():
            if column not in columns:
                cursor.execute(
                    "ALTER TABLE `{}` ADD COLUMN `{}` {}".format(table, column, definition)
                )
                columns.add(column)

        if not has_unique_email:
            cursor.execute(
                "ALTER TABLE `{}` ADD UNIQUE KEY `{}` (`email`)".format(table, index_name)
            )


def main():
    connection = connect_database("mysql")
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT TABLE_NAME FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE()"
            )
            existing_tables = {row["TABLE_NAME"] for row in cursor.fetchall()}
        missing_tables = set(TABLES.values()) - existing_tables
        if missing_tables:
            raise RuntimeError(
                "Tabelas não encontradas no banco configurado: {}.".format(
                    ", ".join(sorted(missing_tables))
                )
            )

        for table_key, table in TABLES.items():
            migrate_table(connection, table, "uq_{}_email".format(table_key))
        connection.commit()
        print("Migração concluída; as tabelas e os registros existentes foram preservados.")
    except (pymysql.MySQLError, RuntimeError):
        connection.rollback()
        logging.exception("Não foi possível migrar o esquema MySQL.")
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
