"""Hospital HMS - JSON API (Flask + PostgreSQL). Also serves the static frontend from docs/."""
import os, re, datetime as dt
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from functools import wraps

import psycopg2, psycopg2.extras
from flask import Flask, abort, g, jsonify, request
from flask.json.provider import DefaultJSONProvider
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash


class Provider(DefaultJSONProvider):
    sort_keys = False  # keep column order for the dashboard tables

    @staticmethod
    def default(o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, dt.datetime):
            return o.isoformat(timespec="minutes")
        if isinstance(o, dt.date):
            return o.isoformat()
        if isinstance(o, dt.time):
            return o.strftime("%H:%M")
        return DefaultJSONProvider.default(o)


app = Flask(__name__, static_folder="docs", static_url_path="")
app.json = Provider(app)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
ser = URLSafeTimedSerializer(app.secret_key, salt="hms-auth")
SLOTS = [f"{h:02d}:{m:02d}" for h in range(9, 17) for m in (0, 30)]  # 09:00 .. 16:30


# ---------------------------------------------------------------- database
def db():
    if "db" not in g:
        g.db = psycopg2.connect(os.environ["DATABASE_URL"], cursor_factory=psycopg2.extras.RealDictCursor)
    return g.db


@app.teardown_appcontext
def close_db(_):
    conn = g.pop("db", None)
    if conn:
        conn.close()


@contextmanager
def tx():
    """One transaction: commit on success, roll back on any error."""
    conn = db()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def run(sql, args=None, one=False):
    with tx() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall() if cur.description else []
    return (rows[0] if rows else None) if one else rows


def friendly(e):
    code = getattr(e, "pgcode", None)
    if code == "P0001":  # RAISE EXCEPTION from our procedures/triggers
        return e.diag.message_primary
    if code == "23505":
        return "That record (or time slot) already exists."
    if code == "23503":
        return "This record is linked to other data, so that action isn't allowed."
    if code in ("23514", "22P02", "22007", "22008", "23502"):
        return "Invalid input - please check the values you entered."
    return "Something went wrong with the database request. Please try again."


@app.errorhandler(psycopg2.Error)
def db_error(e):
    return jsonify(error=friendly(e)), 400


@app.errorhandler(HTTPException)
def http_error(e):
    return jsonify(error="Not found." if e.code == 404 else e.description), e.code


@app.errorhandler(KeyError)
@app.errorhandler(ValueError)
def bad_input(e):
    return jsonify(error="Missing or invalid input."), 400


@app.before_request
def preflight():
    if request.method == "OPTIONS":
        return "", 204


@app.after_request
def cors(r):  # lets the frontend live on GitHub Pages while the API lives elsewhere
    r.headers["Access-Control-Allow-Origin"] = os.environ.get("CORS_ORIGIN", "*")
    r.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    r.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return r


# -------------------------------------------------------------------- auth
def current_user():
    h = request.headers.get("Authorization", "")
    if h.startswith("Bearer "):
        try:
            return ser.loads(h[7:], max_age=12 * 3600)
        except BadSignature:  # also covers expiry
            return None


def roles(*allowed):
    def deco(f):
        @wraps(f)
        def wrapper(*a, **k):
            g.user = current_user()
            if not g.user:
                return jsonify(error="Please log in."), 401
            if allowed and g.user["role"] not in allowed:
                return jsonify(error="You don't have permission to do that."), 403
            return f(*a, **k)
        return wrapper
    return deco


def body():
    return request.get_json(silent=True) or {}


@app.post("/api/login")
def login():
    b = body()
    u = run("SELECT * FROM users WHERE username=%s", (str(b.get("username", "")).strip(),), one=True)
    if not u or not check_password_hash(u["password_hash"], str(b.get("password", ""))):
        return jsonify(error="Invalid username or password."), 401
    user = {"id": u["user_id"], "name": u["username"], "role": u["role"], "doctor_id": u["doctor_id"]}
    return jsonify(token=ser.dumps(user), user=user)


@app.route("/")
def index():
    return app.send_static_file("index.html")


# --------------------------------------------------------------- dashboard
REPORTS = [
    ("Appointments per department",
     """SELECT dep.name AS department, COUNT(*) AS appointments
        FROM appointment a JOIN doctor d ON d.doctor_id = a.doctor_id
        JOIN department dep ON dep.dept_id = d.dept_id
        WHERE a.status <> 'Cancelled' GROUP BY dep.name ORDER BY appointments DESC"""),
    ("Revenue by month",
     "SELECT TO_CHAR(paid_on, 'YYYY-MM') AS month, SUM(amount) AS revenue FROM payment GROUP BY 1 ORDER BY 1 DESC LIMIT 6"),
    ("Busiest doctors (visits)",
     """SELECT d.name AS doctor, COUNT(v.visit_id) AS visits FROM doctor d
        JOIN visit v ON v.doctor_id = d.doctor_id GROUP BY d.name ORDER BY visits DESC LIMIT 5"""),
    ("Largest outstanding bills",
     "SELECT bill_id, patient, balance FROM v_bill_summary WHERE balance > 0 ORDER BY balance DESC LIMIT 5"),
    ("Low-stock medicines",
     "SELECT name, stock FROM medicine WHERE stock < 150 ORDER BY stock LIMIT 5"),
]


@app.get("/api/dashboard")
@roles()
def dashboard():
    stats = run("""SELECT (SELECT COUNT(*) FROM patient) AS patients,
                          (SELECT COUNT(*) FROM doctor) AS doctors,
                          (SELECT COUNT(*) FROM appointment WHERE appt_date = CURRENT_DATE AND status = 'Booked') AS today,
                          (SELECT COALESCE(SUM(balance), 0) FROM v_bill_summary) AS outstanding""", one=True)
    mine = []
    if g.user["role"] == "doctor":
        mine = run("""SELECT * FROM v_doctor_schedule WHERE doctor_id=%s AND appt_date=CURRENT_DATE
                      AND status <> 'Cancelled' ORDER BY slot_time""", (g.user["doctor_id"],))
    return jsonify(stats=stats, mine=mine, reports=[{"title": t, "rows": run(q)} for t, q in REPORTS])


@app.get("/api/lookups")
@roles()
def lookups():
    return jsonify(
        patients=run("SELECT patient_id, name, phone FROM patient ORDER BY name"),
        doctors=run("SELECT doctor_id, name, specialization FROM doctor ORDER BY name"),
        departments=run("SELECT dept_id, name FROM department ORDER BY name"))


# ---------------------------------------------------------------- patients
def check_patient(f):
    s = lambda k: str(f.get(k) or "").strip()
    errs = []
    if len(s("name")) < 2:
        errs.append("Name must be at least 2 characters.")
    if s("gender") not in ("Male", "Female", "Other"):
        errs.append("Please choose a gender.")
    if not re.fullmatch(r"\+?\d{7,15}", s("phone")):
        errs.append("Phone must be 7-15 digits.")
    try:
        if dt.date.fromisoformat(s("dob")) > dt.date.today():
            errs.append("Date of birth cannot be in the future.")
    except ValueError:
        errs.append("Please enter a valid date of birth.")
    return errs


def patient_vals(f):
    s = lambda k: str(f.get(k) or "").strip()
    return (s("name"), s("dob"), s("gender"), s("phone"), s("address"), s("blood_group") or None)


@app.get("/api/patients")
@roles()
def patients():
    q, gender, sort = request.args.get("q", "").strip(), request.args.get("gender", ""), request.args.get("sort", "name")
    order = {"name": "name", "youngest": "dob DESC", "newest": "registered_on DESC, patient_id DESC"}.get(sort, "name")
    sql, args = "SELECT *, fn_patient_age(dob) AS age FROM patient WHERE (name ILIKE %s OR phone LIKE %s)", [f"%{q}%", f"%{q}%"]
    if gender:
        sql += " AND gender=%s"
        args.append(gender)
    return jsonify(run(sql + f" ORDER BY {order}", args))


@app.post("/api/patients")
@roles("admin", "receptionist")
def patient_create():
    b = body()
    errs = check_patient(b)
    if errs:
        return jsonify(error=" ".join(errs)), 400
    r = run("""INSERT INTO patient(name,dob,gender,phone,address,blood_group)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING patient_id""", patient_vals(b), one=True)
    return jsonify(patient_id=r["patient_id"]), 201


@app.put("/api/patients/<int:pid>")
@roles("admin", "receptionist")
def patient_update(pid):
    b = body()
    errs = check_patient(b)
    if errs:
        return jsonify(error=" ".join(errs)), 400
    if not run("""UPDATE patient SET name=%s,dob=%s,gender=%s,phone=%s,address=%s,blood_group=%s
                  WHERE patient_id=%s RETURNING 1 AS ok""", patient_vals(b) + (pid,)):
        abort(404)
    return jsonify(patient_id=pid)


@app.get("/api/patients/<int:pid>")
@roles()
def patient_get(pid):
    p = run("SELECT *, fn_patient_age(dob) AS age FROM patient WHERE patient_id=%s", (pid,), one=True)
    if not p:
        abort(404)
    return jsonify(
        patient=p,
        history=run("SELECT * FROM v_patient_history WHERE patient_id=%s ORDER BY visit_date DESC", (pid,)),
        appts=run("SELECT * FROM v_doctor_schedule WHERE patient_id=%s ORDER BY appt_date DESC, slot_time DESC", (pid,)))


@app.delete("/api/patients/<int:pid>")
@roles("admin", "receptionist")
def patient_delete(pid):
    run("DELETE FROM patient WHERE patient_id=%s", (pid,))
    return jsonify(ok=True)


# ----------------------------------------------------------------- doctors
@app.get("/api/doctors")
@roles()
def doctors():
    return jsonify(run("""SELECT d.*, dep.name AS department FROM doctor d
                          JOIN department dep ON dep.dept_id = d.dept_id ORDER BY d.name"""))


@app.post("/api/doctors")
@roles("admin")
def doctor_create():
    b = body()
    if len(str(b.get("password") or "")) < 6:
        return jsonify(error="Password must be at least 6 characters."), 400
    s = lambda k: str(b.get(k) or "").strip()
    with tx() as cur:  # doctor + login account succeed or fail together
        cur.execute("""INSERT INTO doctor(name,dept_id,specialization,phone,email,consultation_fee)
                       VALUES (%s,%s,%s,%s,%s,%s) RETURNING doctor_id""",
                    (s("name"), b.get("dept_id"), s("specialization"), s("phone"), s("email"), b.get("fee")))
        did = cur.fetchone()["doctor_id"]
        cur.execute("INSERT INTO users(username,password_hash,role,doctor_id) VALUES (%s,%s,'doctor',%s)",
                    (s("username"), generate_password_hash(b["password"]), did))
    return jsonify(doctor_id=did), 201


@app.delete("/api/doctors/<int:did>")
@roles("admin")
def doctor_delete(did):
    run("DELETE FROM doctor WHERE doctor_id=%s", (did,))
    return jsonify(ok=True)


# ------------------------------------------------------------ appointments
@app.get("/api/appointments")
@roles()
def appointments():
    f = request.args
    sql, args = "SELECT * FROM v_doctor_schedule WHERE TRUE", []
    if g.user["role"] == "doctor":
        sql += " AND doctor_id=%s"
        args.append(g.user["doctor_id"])
    elif f.get("doctor_id"):
        sql += " AND doctor_id=%s"
        args.append(f["doctor_id"])
    if f.get("date"):
        sql += " AND appt_date=%s"
        args.append(f["date"])
    if f.get("status"):
        sql += " AND status=%s"
        args.append(f["status"])
    order = "appt_date, slot_time" if f.get("sort") == "oldest" else "appt_date DESC, slot_time"
    return jsonify(run(sql + " ORDER BY " + order + " LIMIT 200", args))


@app.post("/api/appointments")
@roles("admin", "receptionist")
def book():
    b = body()
    r = run("CALL sp_book_appointment(%s::int,%s::int,%s::date,%s::time,%s,NULL::int)",
            (b.get("patient_id") or None, b.get("doctor_id") or None, b.get("appt_date") or None,
             b.get("slot_time") or None, str(b.get("reason") or "").strip()[:200]), one=True)
    return jsonify(appointment_id=r["p_id"]), 201


@app.get("/api/slots")
@roles()
def slots():
    taken = run("""SELECT to_char(slot_time,'HH24:MI') AS t FROM appointment
                   WHERE doctor_id=%s AND appt_date=%s AND status <> 'Cancelled'""",
                (request.args.get("doctor_id"), request.args.get("date")))
    t = {r["t"] for r in taken}
    return jsonify([s for s in SLOTS if s not in t])


@app.post("/api/appointments/<int:aid>/cancel")
@roles("admin", "receptionist")
def cancel(aid):
    run("UPDATE appointment SET status='Cancelled' WHERE appointment_id=%s AND status='Booked'", (aid,))
    return jsonify(ok=True)


@app.post("/api/appointments/<int:aid>/start")
@roles("admin", "doctor")
def start_visit(aid):
    did = g.user["doctor_id"] if g.user["role"] == "doctor" else None
    r = run("""WITH v AS (
                 INSERT INTO visit(appointment_id, patient_id, doctor_id)
                 SELECT appointment_id, patient_id, doctor_id FROM appointment
                 WHERE appointment_id=%(a)s AND status='Booked' AND (%(d)s::int IS NULL OR doctor_id=%(d)s::int)
                 RETURNING visit_id),
               u AS (UPDATE appointment SET status='Completed'
                     WHERE appointment_id=%(a)s AND status='Booked' AND (%(d)s::int IS NULL OR doctor_id=%(d)s::int))
               SELECT visit_id FROM v""", {"a": aid, "d": did}, one=True)
    if not r and (did is None or run("SELECT 1 FROM appointment WHERE appointment_id=%s AND doctor_id=%s", (aid, did))):
        r = run("SELECT visit_id FROM visit WHERE appointment_id=%s", (aid,), one=True)
    if not r:
        abort(404)
    return jsonify(visit_id=r["visit_id"])


# ------------------------------------------------------------------ visits
def check_editable(vid):
    v = run("SELECT doctor_id FROM visit WHERE visit_id=%s", (vid,), one=True)
    if not v:
        abort(404)
    if g.user["role"] == "doctor" and v["doctor_id"] != g.user["doctor_id"]:
        abort(403)


@app.get("/api/visits/<int:vid>")
@roles()
def visit_get(vid):
    v = run("""SELECT v.*, p.name AS patient, fn_patient_age(p.dob) AS age, d.name AS doctor, b.bill_id
               FROM visit v JOIN patient p ON p.patient_id = v.patient_id
               JOIN doctor d ON d.doctor_id = v.doctor_id
               LEFT JOIN bill b ON b.visit_id = v.visit_id WHERE v.visit_id=%s""", (vid,), one=True)
    if not v:
        abort(404)
    u = g.user
    can_edit = u["role"] == "admin" or (u["role"] == "doctor" and u["doctor_id"] == v["doctor_id"])
    return jsonify(
        visit=v, can_edit=can_edit,
        dx=run("SELECT * FROM diagnosis WHERE visit_id=%s ORDER BY diagnosis_id", (vid,)),
        rx=run("""SELECT pr.*, m.name AS medicine, pr.quantity*m.unit_price AS cost FROM prescription pr
                  JOIN medicine m ON m.medicine_id = pr.medicine_id WHERE pr.visit_id=%s ORDER BY pr.prescription_id""", (vid,)),
        tests=run("""SELECT vt.*, t.name, t.price FROM visit_test vt JOIN lab_test t ON t.test_id = vt.test_id
                     WHERE vt.visit_id=%s ORDER BY vt.visit_test_id""", (vid,)),
        meds=run("SELECT medicine_id, name, stock FROM medicine WHERE stock > 0 ORDER BY name") if can_edit else [],
        labs=run("SELECT test_id, name, price FROM lab_test ORDER BY name") if can_edit else [])


@app.post("/api/visits/<int:vid>/diagnosis")
@roles("admin", "doctor")
def add_diagnosis(vid):
    check_editable(vid)
    b = body()
    desc = str(b.get("description") or "").strip()
    if not desc:
        return jsonify(error="Diagnosis description is required."), 400
    run("INSERT INTO diagnosis(visit_id,description,severity) VALUES (%s,%s,%s)",
        (vid, desc[:200], b.get("severity") or "Mild"))
    return jsonify(ok=True), 201


@app.post("/api/visits/<int:vid>/prescribe")
@roles("admin", "doctor")
def prescribe(vid):
    check_editable(vid)
    try:
        rows = [(vid, int(i["medicine_id"]), str(i.get("dosage") or "").strip() or "As directed",
                 int(i.get("days") or 1), int(i["quantity"])) for i in (body().get("items") or [])]
    except (KeyError, ValueError, TypeError):
        return jsonify(error="Days and quantity must be whole numbers."), 400
    if not rows:
        return jsonify(error="Add at least one medicine."), 400
    with tx() as cur:  # TRANSACTION: every medicine is saved (and stock reduced) or none are
        for r in rows:
            cur.execute("INSERT INTO prescription(visit_id,medicine_id,dosage,days,quantity) VALUES (%s,%s,%s,%s,%s)", r)
    return jsonify(count=len(rows)), 201


@app.post("/api/visits/<int:vid>/tests")
@roles("admin", "doctor")
def order_test(vid):
    check_editable(vid)
    run("INSERT INTO visit_test(visit_id,test_id) VALUES (%s,%s)", (vid, body().get("test_id")))
    return jsonify(ok=True), 201


@app.post("/api/visits/<int:vid>/tests/<int:tid>/result")
@roles("admin", "doctor")
def test_result(vid, tid):
    check_editable(vid)
    run("UPDATE visit_test SET result=%s WHERE visit_test_id=%s AND visit_id=%s",
        (str(body().get("result") or "").strip(), tid, vid))
    return jsonify(ok=True)


@app.post("/api/visits/<int:vid>/bill")
@roles("admin", "receptionist")
def make_bill(vid):
    r = run("CALL sp_generate_bill(%s::int, NULL::int)", (vid,), one=True)
    return jsonify(bill_id=r["p_bill"])


# ----------------------------------------------------------------- billing
@app.get("/api/bills")
@roles("admin", "receptionist")
def bills():
    status, sort = request.args.get("status", ""), request.args.get("sort", "newest")
    order = {"newest": "created_at DESC", "balance": "balance DESC", "patient": "patient"}.get(sort, "created_at DESC")
    sql, args = "SELECT * FROM v_bill_summary WHERE TRUE", []
    if status:
        sql += " AND status=%s"
        args.append(status)
    return jsonify(run(sql + f" ORDER BY {order} LIMIT 200", args))


@app.get("/api/bills/<int:bid>")
@roles("admin", "receptionist")
def bill_get(bid):
    b = run("SELECT * FROM v_bill_summary WHERE bill_id=%s", (bid,), one=True)
    if not b:
        abort(404)
    items = run("""SELECT 'Consultation' AS item, 1 AS qty, d.consultation_fee AS amount
                   FROM visit v JOIN doctor d ON d.doctor_id = v.doctor_id WHERE v.visit_id=%(v)s
                   UNION ALL
                   SELECT 'Medicine: ' || m.name, pr.quantity, pr.quantity * m.unit_price
                   FROM prescription pr JOIN medicine m ON m.medicine_id = pr.medicine_id WHERE pr.visit_id=%(v)s
                   UNION ALL
                   SELECT 'Test: ' || t.name, 1, t.price
                   FROM visit_test vt JOIN lab_test t ON t.test_id = vt.test_id WHERE vt.visit_id=%(v)s""",
                {"v": b["visit_id"]})
    return jsonify(bill=b, items=items, payments=run("SELECT * FROM payment WHERE bill_id=%s ORDER BY paid_on", (bid,)))


@app.post("/api/bills/<int:bid>/pay")
@roles("admin", "receptionist")
def pay(bid):
    b = body()
    try:
        amount = Decimal(str(b.get("amount", "")))
    except InvalidOperation:
        return jsonify(error="Enter a valid payment amount."), 400
    run("CALL sp_record_payment(%s::int, %s::numeric, %s)", (bid, amount, b.get("method", "")))
    return jsonify(ok=True), 201


if __name__ == "__main__":
    app.run(debug=True)
