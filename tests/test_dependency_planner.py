from pathlib import Path
import unittest

from domain.dependency_planner import plan_generation
from domain.ddl_parser import parse_ddl


TASK_DIR = Path(__file__).parents[1] / "task"


def _create_phases(plan):
    return [phase.tables for phase in plan.phases if phase.kind == "create"]


class DependencyPlannerTests(unittest.TestCase):
    def test_restaurant_order_is_parent_first_and_alphabetical_within_phase(self) -> None:
        plan = plan_generation(parse_ddl((TASK_DIR / "restrurants_schema.ddl").read_text()))

        self.assertEqual(
            _create_phases(plan),
            [
                ("Customers", "Delivery_Drivers", "Restaurants"),
                ("Menu", "Orders", "Reviews"),
                ("Order_Items",),
            ],
        )
        self.assertTrue(plan.is_supported)
        self.assertEqual(plan.cycles, ())

    def test_company_order_keeps_parents_before_dependents(self) -> None:
        plan = plan_generation(parse_ddl((TASK_DIR / "company_employee_schema.ddl").read_text()))

        self.assertEqual(
            _create_phases(plan),
            [
                ("Companies",),
                ("Departments", "Projects"),
                ("Employees",),
                ("Employee_Benefits", "Employee_Projects", "Performance_Reviews"),
            ],
        )

    def test_library_cycle_is_deferred_after_nullable_seed_rows(self) -> None:
        plan = plan_generation(parse_ddl((TASK_DIR / "library_mgm_schema.ddl").read_text()))

        self.assertTrue(plan.is_supported)
        self.assertEqual(len(plan.cycles), 1)
        cycle = plan.cycles[0]
        self.assertEqual(cycle.tables, ("Departments", "Employees", "Library_Branches"))
        self.assertTrue(cycle.supported)
        self.assertEqual(
            {(relationship.source_table, relationship.source_columns, relationship.referenced_table)
             for relationship in cycle.relationships},
            {
                ("Departments", ("manager_id",), "Employees"),
                ("Employees", ("branch_id",), "Library_Branches"),
                ("Employees", ("department_id",), "Departments"),
                ("Library_Branches", ("manager_id",), "Employees"),
            },
        )
        self.assertEqual(plan.phases[1].kind, "deferred_update")
        self.assertEqual(len(plan.phases[1].relationships), 4)

    def test_self_reference_is_deferred(self) -> None:
        schema = parse_ddl(
            """
            CREATE TABLE employees (
                id INT PRIMARY KEY,
                manager_id INT,
                FOREIGN KEY (manager_id) REFERENCES employees(id)
            );
            """
        )

        plan = plan_generation(schema)

        self.assertTrue(plan.is_supported)
        self.assertEqual(plan.cycles[0].tables, ("employees",))
        self.assertEqual(plan.phases[1].kind, "deferred_update")

    def test_required_cycle_is_reported_as_unsupported(self) -> None:
        schema = parse_ddl(
            """
            CREATE TABLE alpha (id INT PRIMARY KEY, beta_id INT NOT NULL,
                FOREIGN KEY (beta_id) REFERENCES beta(id));
            CREATE TABLE beta (id INT PRIMARY KEY, alpha_id INT,
                FOREIGN KEY (alpha_id) REFERENCES alpha(id));
            """
        )

        plan = plan_generation(schema)

        self.assertFalse(plan.is_supported)
        self.assertFalse(plan.cycles[0].supported)
        self.assertIn("NOT NULL", plan.cycles[0].status)
        self.assertFalse(any(phase.kind == "deferred_update" for phase in plan.phases))


if __name__ == "__main__":
    unittest.main()
