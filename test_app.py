"""End-to-end tests: HTTP request -> Flask API -> PostgreSQL -> JSON response."""
import datetime as dt
import pytest
import init_db
from app import app, run


@pytest.fixture(scope="module")
def client():
    init_db.main()
    app.config.update(TESTING=True)
    with app.test_client() as c:
        yield c


def auth(c, u, p):
    r = c.post("/api/login", json={"username": u, "password": p})
    assert r.status_code == 200
    return {"Authorization": "Bearer " + r.get_json()["token"]}


def test_frontend_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and b"MediCare HMS" in r.data
    assert client.get("/app.js").status_code == 200


def test_api_requires_login(client):
    assert client.get("/api/patients").status_code == 401


def test_bad_login(client):
    r = client.post("/api/login", json={"username": "admin", "password": "nope"})
    assert r.status_code == 401 and "Invalid" in r.get_json()["error"]


def test_patient_crud_and_validation(client):
    h = auth(client, "reception", "reception123")
    bad = client.post("/api/patients", headers=h, json={"name": "A", "dob": "2999-01-01", "gender": "Male", "phone": "12"})
    assert bad.status_code == 400 and "at least 2 characters" in bad.get_json()["error"]
    ok = client.post("/api/patients", headers=h, json={"name": "Test Person", "dob": "1990-05-05", "gender": "Female", "phone": "9123456789"})
    assert ok.status_code == 201
    pid = ok.get_json()["patient_id"]
    assert client.get(f"/api/patients/{pid}", headers=h).get_json()["patient"]["name"] == "Test Person"
    assert client.put(f"/api/patients/{pid}", headers=h, json={"name": "Renamed", "dob": "1990-05-05", "gender": "Female", "phone": "9123456789"}).status_code == 200
    assert client.delete(f"/api/patients/{pid}", headers=h).status_code == 200


def test_duplicate_slot_is_prevented(client):
    h = auth(client, "admin", "admin123")
    day = (dt.date.today() + dt.timedelta(days=40)).isoformat()
    data = {"patient_id": 1, "doctor_id": 1, "appt_date": day, "slot_time": "10:00", "reason": "test"}
    assert client.post("/api/appointments", headers=h, json=data).status_code == 201
    assert "10:00" not in client.get(f"/api/slots?doctor_id=1&date={day}", headers=h).get_json()
    data["patient_id"] = 2
    r = client.post("/api/appointments", headers=h, json=data)
    assert r.status_code == 400 and "already has an appointment" in r.get_json()["error"]
    n = run("SELECT COUNT(*) AS n FROM appointment WHERE doctor_id=1 AND appt_date=%s AND slot_time='10:00'", (day,), one=True)
    assert n["n"] == 1


def test_role_based_access(client):
    h = auth(client, "reception", "reception123")
    assert client.post("/api/doctors", headers=h, json={}).status_code == 403
    d = auth(client, "doctor1", "doctor123")
    assert client.get("/api/bills", headers=d).status_code == 403


def test_prescription_transaction_rolls_back(client):
    h = auth(client, "admin", "admin123")
    vid = run("SELECT visit_id FROM visit LIMIT 1", one=True)["visit_id"]
    before = run("SELECT stock FROM medicine WHERE medicine_id=1", one=True)["stock"]
    items = [{"medicine_id": 1, "dosage": "1-0-1", "days": 3, "quantity": 2},
             {"medicine_id": 2, "dosage": "1-0-1", "days": 3, "quantity": 999999}]
    r = client.post(f"/api/visits/{vid}/prescribe", headers=h, json={"items": items})
    assert r.status_code == 400 and "Insufficient stock" in r.get_json()["error"]
    assert run("SELECT stock FROM medicine WHERE medicine_id=1", one=True)["stock"] == before  # first insert undone


def test_payment_cannot_exceed_balance(client):
    h = auth(client, "admin", "admin123")
    bill = run("SELECT bill_id FROM v_bill_summary WHERE balance > 0 LIMIT 1", one=True)["bill_id"]
    r = client.post(f"/api/bills/{bill}/pay", headers=h, json={"amount": "99999999", "method": "Cash"})
    assert r.status_code == 400 and "exceeds the balance" in r.get_json()["error"]
