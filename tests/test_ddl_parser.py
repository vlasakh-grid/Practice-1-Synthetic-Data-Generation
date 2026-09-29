from pathlib import Path
import unittest

from domain.ddl_parser import DDLParseError, parse_ddl


TASK_DIR = Path(__file__).parents[1] / "task"


class DDLParserTests(unittest.TestCase):
    def test_library_schema_parses_columns_and_alter_table_foreign_key(self) -> None:
        schema = parse_ddl((TASK_DIR / "library_mgm_schema.ddl").read_text())

        self.assertEqual(len(schema.tables), 9)
        members = schema.table("Library_Members")
        self.assertEqual(members.column("account_status").enum_values, ["Active", "Inactive", "Suspended", "Closed"])
        self.assertEqual(members.column("account_status").default, "'Active'")
        self.assertTrue(members.column("email").is_unique)
        branches = schema.table("Library_Branches")
        self.assertEqual(branches.foreign_keys[0].referenced_table, "Employees")

    def test_restaurant_schema_parses_checks_and_mysql_type_mapping(self) -> None:
        schema = parse_ddl((TASK_DIR / "restrurants_schema.ddl").read_text())

        reviews = schema.table("Reviews")
        rating = reviews.column("rating")
        self.assertEqual(rating.postgres_type, "INTEGER")
        self.assertEqual(rating.checks[0].expression, "rating >= 1 AND rating <= 5")
        self.assertEqual(schema.table("Customers").column("registration_date").postgres_type, "TIMESTAMP")

    def test_company_schema_parses_self_references(self) -> None:
        schema = parse_ddl((TASK_DIR / "company_employee_schema.ddl").read_text())

        reviews = schema.table("Performance_Reviews")
        self.assertEqual(len(reviews.foreign_keys), 2)
        self.assertEqual({fk.referenced_table for fk in reviews.foreign_keys}, {"Employees"})
        self.assertEqual(reviews.column("review_status").enum_values, ["Draft", "Final", "Approved"])

    def test_named_composite_constraints_and_inline_reference(self) -> None:
        schema = parse_ddl(
            """
            CREATE TABLE child (
                parent_id INT REFERENCES parent(id) ON DELETE CASCADE,
                code VARCHAR(10),
                CONSTRAINT child_pk PRIMARY KEY (parent_id, code),
                CONSTRAINT child_code_unique UNIQUE (code),
                CONSTRAINT code_check CHECK (code IN ('A', 'B'))
            );
            """
        )

        child = schema.table("child")
        self.assertEqual(child.primary_key, ["parent_id", "code"])
        self.assertEqual(child.foreign_keys[0].columns, ["parent_id"])
        self.assertEqual(child.foreign_keys[0].on_delete, "CASCADE")
        self.assertTrue(child.column("code").is_unique)
        self.assertEqual(child.checks[0].expression, "code IN ('A', 'B')")

    def test_missing_create_statement_is_reported(self) -> None:
        with self.assertRaises(DDLParseError):
            parse_ddl("ALTER TABLE example ADD COLUMN name TEXT;")


if __name__ == "__main__":
    unittest.main()
