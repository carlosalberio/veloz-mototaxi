import os
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient


class OrderAndRideServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.previous_database_path = os.environ.get("VELOZ_SQLITE_PATH")
        cls.previous_backend = os.environ.get("VELOZ_DATABASE_BACKEND")
        os.environ["VELOZ_SQLITE_PATH"] = os.path.join(cls.temp_dir.name, "veloz_test.sqlite3")
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
                    "name": "Carlos Cliente",
                    "age": 28,
                    "email": cls.customer_email,
                    "phone": "87999887766",
                    "password": "SenhaSegura123",
                },
            )
            driver = client.post(
                "/api/register",
                json={
                    "accountType": "mototaxista",
                    "name": "Marcos Mototaxista",
                    "age": 35,
                    "email": cls.driver_email,
                    "phone": "87988776655",
                    "password": "SenhaSegura123",
                    "cpf": "12345678909",
                    "cnh": "12345678909",
                    "cnhCategory": "A",
                    "cnhExpiry": "2030-01-01",
                    "motorcycle": "Honda Bros 160",
                    "plate": "PEA1B23",
                },
            )

        if customer.status_code != 201 or driver.status_code != 201:
            raise AssertionError(f"Falha ao registrar usuários de teste: {customer.text} {driver.text}")

        cls.customer = TestClient(cls.app)
        cls.driver = TestClient(cls.app)

        cls.login(cls.customer, "cliente", cls.customer_email)
        cls.login(cls.driver, "mototaxista", cls.driver_email)

        # Set driver online
        online_res = cls.driver.put("/api/driver/availability", json={"online": True})
        if online_res.status_code != 200:
            raise AssertionError(f"Falha ao colocar motorista online: {online_res.text}")

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

    @classmethod
    def login(cls, client: TestClient, account_type: str, email: str) -> None:
        response = client.post(
            "/api/login",
            json={"accountType": account_type, "email": email, "password": "SenhaSegura123"},
        )
        assert response.status_code == 200, response.text

    def test_legacy_route_redirects(self) -> None:
        """Verifica que as rotas antigas de entregas e de autenticação redirecionam corretamente."""
        res_entrega = self.customer.get("/entrega", follow_redirects=False)
        self.assertEqual(res_entrega.status_code, 303)
        self.assertEqual(res_entrega.headers["location"], "/#enviar-pedido")

        res_admin = self.customer.get("/admin-entregas", follow_redirects=False)
        self.assertEqual(res_admin.status_code, 303)
        self.assertEqual(res_admin.headers["location"], "/inicio")

        with TestClient(self.app) as anon:
            res_login = anon.get("/login", follow_redirects=False)
            self.assertEqual(res_login.status_code, 303)
            self.assertEqual(res_login.headers["location"], "/#login")

            res_cadastro = anon.get("/cadastro", follow_redirects=False)
            self.assertEqual(res_cadastro.status_code, 303)
            self.assertEqual(res_cadastro.headers["location"], "/#cadastro")

            res_login_query = anon.get("/login?tipo=mototaxista", follow_redirects=False)
            self.assertEqual(res_login_query.status_code, 303)
            self.assertEqual(res_login_query.headers["location"], "/?tipo=mototaxista#login")

    def test_passenger_ride_creation_and_payload(self) -> None:
        """Criação de corrida convencional de passageiro preserva o comportamento existente."""
        payload = {
            "service_type": "passageiro",
            "pickup": "Praça Sérgio Magalhães, Serra Talhada",
            "destination": "Shopping Serra Talhada",
            "pickup_lat": -7.9868,
            "pickup_lng": -38.2920,
            "destination_lat": -7.9912,
            "destination_lng": -38.3006,
            "is_immediate": True,
            "payment_method": "Dinheiro",
            "idempotency_key": str(uuid.uuid4()),
        }
        response = self.customer.post("/api/rides", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        self.assertEqual(data["service_type"], "passageiro")
        self.assertEqual(data["amount_cents"], 700)
        self.assertEqual(data["status"], "solicitada")

    def test_order_service_creation_and_auto_fill(self) -> None:
        """Enviar pedido: dados do solicitante vêm do cadastro, campos mínimos de origem e destino."""
        payload = {
            "service_type": "pedido",
            "pickup": "Rua Enock Ignácio de Oliveira, 100",
            "destination": "Avenida Afonso Magalhães, 500",
            "pickup_lat": -7.9868,
            "pickup_lng": -38.2920,
            "destination_lat": -7.9912,
            "destination_lng": -38.3006,
            "is_immediate": True,
            "payment_method": "Dinheiro",
            "idempotency_key": str(uuid.uuid4()),
        }
        response = self.customer.post("/api/rides", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        self.assertEqual(data["service_type"], "pedido")
        self.assertEqual(data["amount_cents"], 700)
        self.assertEqual(data["status"], "solicitada")

        ride_id = data["id"]
        # Detalhes consultados pelo motorista após aceitar ou cliente no histórico
        history_res = self.customer.get("/api/rides/mine")
        self.assertEqual(history_res.status_code, 200)
        my_ride = next((r for r in history_res.json()["rides"] if r["id"] == ride_id), None)
        self.assertIsNotNone(my_ride)
        self.assertEqual(my_ride["service_type"], "pedido")
        self.assertEqual(my_ride["pickup"], payload["pickup"])
        self.assertEqual(my_ride["destination"], payload["destination"])

        # Cancel the ride to keep state clean
        cancel_res = self.customer.post(f"/api/rides/{ride_id}/cancel")
        self.assertEqual(cancel_res.status_code, 200)

    def test_driver_identifies_service_type_and_completes_order(self) -> None:
        """Mototaxista visualiza solicitações disponíveis com tipo de serviço, aceita e conclui pedido."""
        # Cliente cria um pedido
        order_res = self.customer.post(
            "/api/rides",
            json={
                "service_type": "pedido",
                "pickup": "Farmácia Central, Serra Talhada",
                "destination": "Bairro Nossa Senhora da Penha",
                "pickup_lat": -7.9868,
                "pickup_lng": -38.2920,
                "destination_lat": -7.9912,
                "destination_lng": -38.3006,
                "is_immediate": True,
                "payment_method": "Dinheiro",
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        self.assertEqual(order_res.status_code, 201)
        order_data = order_res.json()
        order_id = order_data["id"]

        # Motorista consulta disponíveis
        avail_res = self.driver.get("/api/driver/rides/available")
        self.assertEqual(avail_res.status_code, 200)
        avail_rides = avail_res.json()["rides"]

        # Localiza o pedido recém-criado
        matching = [r for r in avail_rides if r["id"] == order_id]
        self.assertEqual(len(matching), 1)
        target = matching[0]
        self.assertEqual(target["service_type"], "pedido")
        self.assertEqual(target["pickup"], "Farmácia Central, Serra Talhada")
        self.assertEqual(target["destination"], "Bairro Nossa Senhora da Penha")

        # Motorista aceita a solicitação de pedido
        accept_res = self.driver.post(f"/api/driver/rides/{order_id}/accept")
        self.assertEqual(accept_res.status_code, 200, accept_res.text)

        # Motorista inicia o deslocamento / entrega
        start_res = self.driver.patch(
            f"/api/driver/rides/{order_id}/status",
            json={"status": "em_andamento"},
        )
        self.assertEqual(start_res.status_code, 200)
        self.assertEqual(start_res.json()["status"], "em_andamento")

        # Motorista conclui a entrega
        complete_res = self.driver.patch(
            f"/api/driver/rides/{order_id}/status",
            json={"status": "concluida"},
        )
        self.assertEqual(complete_res.status_code, 200)
        self.assertEqual(complete_res.json()["status"], "concluida")

        # Cliente visualiza histórico com o pedido concluído
        history_res = self.customer.get("/api/rides/mine")
        self.assertEqual(history_res.status_code, 200)
        completed_order = next((r for r in history_res.json()["rides"] if r["id"] == order_id), None)
        self.assertIsNotNone(completed_order)
        self.assertEqual(completed_order["status"], "concluida")
        self.assertEqual(completed_order["service_type"], "pedido")

        # Motorista visualiza detalhes do pedido com service_type e dados do cliente
        details_res = self.driver.get(f"/api/driver/rides/{order_id}")
        self.assertEqual(details_res.status_code, 200)
        details = details_res.json()
        self.assertEqual(details["service_type"], "pedido")
        self.assertEqual(details["passenger_name"], "Carlos Cliente")
        self.assertEqual(details["passenger_phone"], "87999887766")


if __name__ == "__main__":
    unittest.main()
