import base64
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient


class DriverPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.previous_database_path = os.environ.get("VELOZ_SQLITE_PATH")
        cls.previous_backend = os.environ.get("VELOZ_DATABASE_BACKEND")
        os.environ["VELOZ_SQLITE_PATH"] = os.path.join(cls.temp_dir.name, "test.sqlite3")
        os.environ["VELOZ_DATABASE_BACKEND"] = "sqlite"
        from server import app

        cls.app = app
        cls.suffix = uuid.uuid4().hex[:8]
        cls.customer_email = f"cliente-{cls.suffix}@example.test"
        cls.driver_email = f"mototaxista-{cls.suffix}@example.test"
        with TestClient(cls.app) as client:
            customer = client.post(
                "/api/register",
                json={
                    "accountType": "cliente",
                    "name": "Cliente de teste",
                    "age": 30,
                    "email": cls.customer_email,
                    "phone": "11987654321",
                    "password": "Senha1234",
                },
            )
            driver = client.post(
                "/api/register",
                json=cls.driver_registration(cls.driver_email),
            )
        if customer.status_code != 201 or driver.status_code != 201:
            raise AssertionError(f"Falha ao criar contas de teste: {customer.text} {driver.text}")

    @staticmethod
    def driver_registration(email: str) -> dict[str, object]:
        return {
            "accountType": "mototaxista",
            "name": "Motorista de teste",
            "age": 32,
            "email": email,
            "phone": "11987654321",
            "password": "Senha1234",
            "cpf": "12345678901",
            "cnh": "12345678901",
            "cnhCategory": "A",
            "cnhExpiry": "2099-12-31",
            "motorcycle": "Honda CG",
            "plate": "ABC1D23",
        }

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.previous_database_path is None:
            os.environ.pop("VELOZ_SQLITE_PATH", None)
        else:
            os.environ["VELOZ_SQLITE_PATH"] = cls.previous_database_path
        if cls.previous_backend is None:
            os.environ.pop("VELOZ_DATABASE_BACKEND", None)
        else:
            os.environ["VELOZ_DATABASE_BACKEND"] = cls.previous_backend
        cls.temp_dir.cleanup()

    def login(self, client: TestClient, account_type: str, email: str) -> None:
        response = client.post(
            "/api/login",
            json={"accountType": account_type, "email": email, "password": "Senha1234"},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_role_protection_and_panel_routes(self) -> None:
        with TestClient(self.app) as anonymous:
            self.assertEqual(anonymous.get("/api/driver/dashboard").status_code, 401)
            self.assertEqual(
                anonymous.put("/api/customer/profile", json={"phone": "87987654321"}).status_code,
                401,
            )
            self.assertEqual(anonymous.get("/painel", follow_redirects=False).status_code, 303)

        with TestClient(self.app) as customer:
            self.login(customer, "cliente", self.customer_email)
            self.assertEqual(customer.get("/api/driver/dashboard").status_code, 403)
            panel = customer.get("/painel", follow_redirects=False)
            self.assertEqual(panel.headers["location"], "/inicio")

        with TestClient(self.app) as driver:
            self.login(driver, "mototaxista", self.driver_email)
            page = driver.get("/painel")
            self.assertEqual(page.status_code, 200)
            self.assertIn("Visão geral", page.text)
            self.assertEqual(driver.get("/api/driver/dashboard").status_code, 200)
            self.assertEqual(
                driver.put("/api/customer/profile", json={"phone": "87987654321"}).status_code,
                403,
            )

    def test_persisted_ride_gps_finance_and_exports(self) -> None:
        with TestClient(self.app) as customer, TestClient(self.app) as driver:
            self.login(customer, "cliente", self.customer_email)
            self.login(driver, "mototaxista", self.driver_email)
            self.assertEqual(customer.get("/api/me").json()["user"]["phone"], "11987654321")
            self.assertEqual(driver.get("/api/driver/rides/available").json()["rides"], [])
            self.assertEqual(
                driver.put("/api/driver/availability", json={"online": True}).status_code,
                200,
            )
            scheduled_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
            ride_request = {
                "pickup": "Rua de partida, 100",
                "destination": "Avenida de destino, 200",
                "pickup_lat": -7.9868,
                "pickup_lng": -38.292,
                "destination_lat": -7.9912,
                "destination_lng": -38.3006,
                "scheduled_at": scheduled_at,
                "is_immediate": False,
                "payment_method": "Dinheiro",
                "idempotency_key": str(uuid.uuid4()),
            }
            request = customer.post(
                "/api/rides",
                json=ride_request,
            )
            self.assertEqual(request.status_code, 201, request.text)
            ride_id = request.json()["id"]
            self.assertEqual(request.json()["payment_status"], "pendente")
            outside_service_area = {
                **ride_request,
                "pickup_lat": -7.5,
                "idempotency_key": str(uuid.uuid4()),
            }
            outside_request = customer.post("/api/rides", json=outside_service_area)
            self.assertEqual(outside_request.status_code, 422, outside_request.text)
            duplicate = customer.post("/api/rides", json=ride_request)
            self.assertEqual(duplicate.status_code, 201, duplicate.text)
            self.assertEqual(duplicate.json()["id"], ride_id)
            self.assertTrue(duplicate.json()["duplicate"])
            changed_request = {**ride_request, "destination": "Rua diferente, 300"}
            self.assertEqual(customer.post("/api/rides", json=changed_request).status_code, 409)

            missing_coordinates = dict(ride_request)
            del missing_coordinates["pickup_lat"]
            self.assertEqual(customer.post("/api/rides", json=missing_coordinates).status_code, 422)
            same_location = {
                **ride_request,
                "destination_lat": ride_request["pickup_lat"],
                "destination_lng": ride_request["pickup_lng"],
                "idempotency_key": str(uuid.uuid4()),
            }
            self.assertEqual(customer.post("/api/rides", json=same_location).status_code, 422)
            past_schedule = {
                **ride_request,
                "scheduled_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
                "idempotency_key": str(uuid.uuid4()),
            }
            self.assertEqual(customer.post("/api/rides", json=past_schedule).status_code, 422)
            unsupported_payment = {
                **ride_request,
                "payment_method": "Pix",
                "idempotency_key": str(uuid.uuid4()),
            }
            self.assertEqual(customer.post("/api/rides", json=unsupported_payment).status_code, 422)

            offers = driver.get("/api/driver/rides/available").json()["rides"]
            self.assertEqual(len(offers), 1)
            self.assertEqual(driver.post(f"/api/driver/rides/{ride_id}/accept").status_code, 200)
            driver_details = driver.get(f"/api/driver/rides/{ride_id}").json()
            self.assertEqual(driver_details["passenger_name"], "Cliente de teste")
            self.assertEqual(driver_details["passenger_phone"], "11987654321")
            self.assertNotIn("cliente_email", driver_details)
            self.assertNotIn("chave_idempotencia", driver_details)
            self.assertEqual(
                driver.patch(
                    f"/api/driver/rides/{ride_id}/status",
                    json={"status": "concluida"},
                ).status_code,
                409,
            )
            self.assertEqual(
                driver.patch(
                    f"/api/driver/rides/{ride_id}/status",
                    json={"status": "em_andamento"},
                ).status_code,
                200,
            )
            gps = {
                "latitude": -7.9868,
                "longitude": -38.292,
                "accuracy_m": 8,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
            outside_gps = {**gps, "latitude": -7.5}
            self.assertEqual(
                driver.post(f"/api/driver/rides/{ride_id}/gps", json=outside_gps).status_code,
                422,
            )
            invalid_gps = {**gps, "latitude": 91}
            self.assertEqual(
                driver.post(f"/api/driver/rides/{ride_id}/gps", json=invalid_gps).status_code,
                422,
            )
            self.assertEqual(driver.post(f"/api/driver/rides/{ride_id}/gps", json=gps).status_code, 201)
            self.assertEqual(driver.post(f"/api/driver/rides/{ride_id}/gps", json=gps).status_code, 429)
            self.assertEqual(
                driver.patch(
                    f"/api/driver/rides/{ride_id}/status",
                    json={"status": "concluida"},
                ).status_code,
                200,
            )
            dashboard = driver.get("/api/driver/dashboard?period=30dias").json()
            self.assertEqual(dashboard["metrics"]["completed_rides"], 1)
            self.assertEqual(dashboard["metrics"]["confirmed_earnings_cents"], 0)
            self.assertEqual(dashboard["metrics"]["pending_payments_cents"], 700)
            self.assertGreaterEqual(dashboard["metrics"]["gps_distance_m"], 0)
            self.assertEqual(customer.post(f"/api/rides/{ride_id}/review", json={"stars": 5}).status_code, 201)
            self.assertEqual(customer.post(f"/api/rides/{ride_id}/review", json={"stars": 4}).status_code, 409)
            self.assertEqual(driver.get("/api/driver/reviews").json()["average"], 5)

            invalid_expense = driver.post(
                "/api/driver/expenses",
                json={
                    "category": "Combustível",
                    "description": "Valor inválido",
                    "amount_cents": 0,
                    "spent_on": datetime.now(timezone.utc).date().isoformat(),
                },
            )
            self.assertEqual(invalid_expense.status_code, 422)
            expense = driver.post(
                "/api/driver/expenses",
                json={
                    "category": "Combustível",
                    "description": "=2+2",
                    "amount_cents": 1500,
                    "spent_on": datetime.now(timezone.utc).date().isoformat(),
                },
            )
            self.assertEqual(expense.status_code, 201, expense.text)
            expense_id = expense.json()["id"]
            self.assertEqual(
                driver.put(
                    "/api/driver/goals",
                    json={"period": "mensal", "target_cents": 25000, "target_rides": 10},
                ).status_code,
                200,
            )
            csv_response = driver.get("/api/driver/reports.csv?kind=despesas")
            self.assertEqual(csv_response.status_code, 200)
            self.assertIn("'=2+2", csv_response.text)
            pdf_response = driver.get("/api/driver/reports.pdf?kind=corridas")
            self.assertEqual(pdf_response.status_code, 200)
            self.assertTrue(pdf_response.content.startswith(b"%PDF"))

            image = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jNvkAAAAASUVORK5CYII="
            )
            upload = driver.post(
                "/api/driver/profile/photo",
                content=image,
                headers={"Content-Type": "image/png"},
            )
            self.assertEqual(upload.status_code, 200, upload.text)
            self.assertEqual(driver.get("/api/driver/profile/photo").status_code, 200)
            second_email = f"outro-mototaxista-{self.suffix}@example.test"
            self.assertEqual(
                customer.post("/api/register", json=self.driver_registration(second_email)).status_code,
                201,
            )
            with TestClient(self.app) as another_driver:
                self.login(another_driver, "mototaxista", second_email)
                self.assertEqual(another_driver.get(f"/api/driver/rides/{ride_id}").status_code, 404)
                self.assertEqual(another_driver.put(f"/api/driver/expenses/{expense_id}", json={
                    "category": "Combustível",
                    "description": "Outro usuário",
                    "amount_cents": 100,
                    "spent_on": datetime.now(timezone.utc).date().isoformat(),
                }).status_code, 404)
            self.assertEqual(driver.delete(f"/api/driver/expenses/{expense_id}").status_code, 200)

    def test_immediate_ride_and_authenticated_customer_data(self) -> None:
        with TestClient(self.app) as customer:
            self.login(customer, "cliente", self.customer_email)
            before = datetime.now(timezone.utc)
            response = customer.post(
                "/api/rides",
                json={
                    "pickup": "Praça de embarque",
                    "destination": "Terminal de destino",
                    "pickup_lat": -7.9868,
                    "pickup_lng": -38.292,
                    "destination_lat": -7.9912,
                    "destination_lng": -38.3006,
                    "scheduled_at": None,
                    "is_immediate": True,
                    "payment_method": "Dinheiro",
                    "idempotency_key": str(uuid.uuid4()),
                },
            )
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()["amount_cents"], 700)
            ride = customer.get("/api/rides/mine").json()["rides"][0]
            scheduled = datetime.fromisoformat(ride["scheduled_at"])
            self.assertGreaterEqual(scheduled, before)
            self.assertEqual(ride["status"], "solicitada")
            from database import connect_database

            connection = connect_database()
            try:
                stored_self_passenger = connection.execute(
                    "SELECT passageiro_nome, passageiro_telefone FROM corridas WHERE id = ?",
                    (ride["id"],),
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(stored_self_passenger["passageiro_nome"], "Cliente de teste")
            self.assertEqual(stored_self_passenger["passageiro_telefone"], "11987654321")
            self.assertEqual(customer.post(f"/api/rides/{ride['id']}/cancel").status_code, 200)

            spoofed_self_data = customer.post(
                "/api/rides",
                json={
                    "pickup": "Praça de embarque",
                    "destination": "Terminal de destino",
                    "pickup_lat": -7.9868,
                    "pickup_lng": -38.292,
                    "destination_lat": -7.9912,
                    "destination_lng": -38.3006,
                    "passenger_name": "Outra pessoa",
                    "passenger_phone": "11987654321",
                    "is_immediate": True,
                    "payment_method": "Dinheiro",
                    "idempotency_key": str(uuid.uuid4()),
                },
            )
            self.assertEqual(spoofed_self_data.status_code, 201, spoofed_self_data.text)
            connection = connect_database()
            try:
                stored_self_passenger = connection.execute(
                    "SELECT cliente_email, passageiro_nome, passageiro_telefone FROM corridas WHERE id = ?",
                    (spoofed_self_data.json()["id"],),
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(stored_self_passenger["cliente_email"], self.customer_email)
            self.assertEqual(stored_self_passenger["passageiro_nome"], "Cliente de teste")
            self.assertEqual(stored_self_passenger["passageiro_telefone"], "11987654321")
            self.assertEqual(
                customer.post(f"/api/rides/{spoofed_self_data.json()['id']}/cancel").status_code,
                200,
            )

            missing_other_passenger = customer.post(
                "/api/rides",
                json={
                    "pickup": "Praça de embarque",
                    "destination": "Terminal de destino",
                    "pickup_lat": -7.9868,
                    "pickup_lng": -38.292,
                    "destination_lat": -7.9912,
                    "destination_lng": -38.3006,
                    "is_immediate": True,
                    "for_another_person": True,
                    "payment_method": "Dinheiro",
                    "idempotency_key": str(uuid.uuid4()),
                },
            )
            self.assertEqual(missing_other_passenger.status_code, 422)

            other_person = customer.post(
                "/api/rides",
                json={
                    "pickup": "Praça de embarque",
                    "destination": "Terminal de destino",
                    "pickup_lat": -7.9868,
                    "pickup_lng": -38.292,
                    "destination_lat": -7.9912,
                    "destination_lng": -38.3006,
                    "passenger_name": "Maria de Exemplo",
                    "passenger_phone": "(21) 99876-5432",
                    "scheduled_at": None,
                    "is_immediate": True,
                    "for_another_person": True,
                    "payment_method": "Dinheiro",
                    "idempotency_key": str(uuid.uuid4()),
                },
            )
            self.assertEqual(other_person.status_code, 201, other_person.text)
            from database import connect_database

            connection = connect_database()
            try:
                stored_passenger = connection.execute(
                    "SELECT passageiro_nome, passageiro_telefone FROM corridas WHERE id = ?",
                    (other_person.json()["id"],),
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(stored_passenger["passageiro_nome"], "Maria de Exemplo")
            self.assertEqual(stored_passenger["passageiro_telefone"], "21998765432")
            connection = connect_database()
            try:
                requester_email = connection.execute(
                    "SELECT cliente_email FROM corridas WHERE id = ?",
                    (other_person.json()["id"],),
                ).fetchone()["cliente_email"]
            finally:
                connection.close()
            self.assertEqual(requester_email, self.customer_email)
            self.assertEqual(
                customer.post(f"/api/rides/{other_person.json()['id']}/cancel").status_code,
                200,
            )

    def test_incomplete_customer_profile_can_be_updated_for_self_rides(self) -> None:
        email = f"cliente-incompleto-{self.suffix}@example.test"
        with TestClient(self.app) as customer:
            registered = customer.post(
                "/api/register",
                json={
                    "accountType": "cliente",
                    "name": "Cliente incompleto",
                    "age": 30,
                    "email": email,
                    "phone": "12345678",
                    "password": "Senha1234",
                },
            )
            self.assertEqual(registered.status_code, 201, registered.text)
            self.login(customer, "cliente", email)
            ride = {
                "pickup": "Praça de embarque",
                "destination": "Terminal de destino",
                "pickup_lat": -7.9868,
                "pickup_lng": -38.292,
                "destination_lat": -7.9912,
                "destination_lng": -38.3006,
                "scheduled_at": None,
                "is_immediate": True,
                "payment_method": "Dinheiro",
                "idempotency_key": str(uuid.uuid4()),
            }
            missing_phone = customer.post("/api/rides", json=ride)
            self.assertEqual(missing_phone.status_code, 422)
            self.assertIn("Atualize seu celular", missing_phone.json()["detail"])

            profile_update = customer.put(
                "/api/customer/profile",
                json={"phone": "(87) 98765-4321"},
            )
            self.assertEqual(profile_update.status_code, 200, profile_update.text)
            self.assertEqual(profile_update.json()["phone"], "87987654321")
            self.assertEqual(customer.get("/api/me").json()["user"]["phone"], "87987654321")

            created = customer.post("/api/rides", json=ride)
            self.assertEqual(created.status_code, 201, created.text)
            from database import connect_database

            connection = connect_database()
            try:
                stored_passenger = connection.execute(
                    "SELECT passageiro_nome, passageiro_telefone FROM corridas WHERE id = ?",
                    (created.json()["id"],),
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(stored_passenger["passageiro_nome"], "Cliente incompleto")
            self.assertEqual(stored_passenger["passageiro_telefone"], "87987654321")
            self.assertEqual(customer.post(f"/api/rides/{created.json()['id']}/cancel").status_code, 200)


if __name__ == "__main__":
    unittest.main()
