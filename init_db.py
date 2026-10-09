"""Create the schema and load 400+ sample rows.
Usage: python init_db.py            (reset everything)
       python init_db.py --if-empty (only if the DB has no tables yet; used on deploy)"""
import os, sys, random, datetime as dt
from decimal import Decimal
import psycopg2
from werkzeug.security import generate_password_hash

SLOTS = [f"{h:02d}:{m:02d}" for h in range(9, 17) for m in (0, 30)]
DEPTS = ["Cardiology", "Neurology", "Orthopedics", "Pediatrics", "General Medicine", "Dermatology"]
FIRST = ["Aarav", "Maya", "Liam", "Sofia", "Noah", "Zara", "Ethan", "Priya", "Omar", "Lena", "Arjun", "Chloe",
         "Daniel", "Fatima", "Hugo", "Isha", "Jonas", "Kavya", "Leo", "Mei", "Nina", "Owen", "Rhea", "Sam"]
LAST = ["Sharma", "Khan", "Rossi", "Chen", "Patel", "Novak", "Silva", "Ahmed", "Das", "Nguyen", "Brown", "Roy",
        "Garcia", "Kumar", "Ito", "Mehta", "Walker", "Bose", "Lopez", "Singh"]
MEDS = [("Paracetamol", 2.5, 300), ("Amoxicillin", 8, 300), ("Ibuprofen", 4, 300), ("Cetirizine", 3, 300),
        ("Omeprazole", 6, 300), ("Metformin", 5, 300), ("Atorvastatin", 9, 300), ("Amlodipine", 7, 300),
        ("Azithromycin", 15, 300), ("Salbutamol Inhaler", 60, 130), ("ORS Sachet", 1.5, 300),
        ("Vitamin D3", 12, 300), ("Pantoprazole", 6.5, 300), ("Cough Syrup", 45, 135), ("Hydrocortisone Cream", 35, 140)]
TESTS = [("Complete Blood Count", 350), ("Lipid Profile", 600), ("Blood Glucose", 120), ("Thyroid Panel", 550),
         ("Chest X-Ray", 450), ("ECG", 300), ("MRI Brain", 6000), ("Urine Routine", 150)]
DX = [("Viral fever", "Mild"), ("Hypertension", "Moderate"), ("Type 2 diabetes", "Moderate"), ("Migraine", "Mild"),
      ("Wrist fracture", "Severe"), ("Asthma", "Moderate"), ("Skin allergy", "Mild"), ("Gastritis", "Mild"),
      ("Bronchitis", "Moderate"), ("Anxiety", "Mild")]
REASONS = ["Fever", "Routine check-up", "Chest pain", "Headache", "Skin rash", "Follow-up", "Joint pain", "Cough"]
BLOOD = ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]


def seed(cur):
    rnd, today = random.Random(7), dt.date.today()
    cur.execute("INSERT INTO department(name) VALUES " + ",".join(["(%s)"] * len(DEPTS)), DEPTS)

    hashes = {p: generate_password_hash(p) for p in ("admin123", "reception123", "doctor123")}
    cur.execute("INSERT INTO users(username,password_hash,role) VALUES ('admin',%s,'admin'),('reception',%s,'receptionist')",
                (hashes["admin123"], hashes["reception123"]))

    docs = []
    for i in range(12):
        cur.execute("""INSERT INTO doctor(name,dept_id,specialization,phone,email,consultation_fee)
                       VALUES (%s,%s,%s,%s,%s,%s) RETURNING doctor_id""",
                    (f"Dr. {FIRST[i]} {LAST[i]}", i % 6 + 1, DEPTS[i % 6], f"98000{i:05d}",
                     f"doctor{i + 1}@hospital.test", rnd.choice([300000, 400000, 500000, 600000, 550000])))
        did = cur.fetchone()[0]
        docs.append(did)
        cur.execute("INSERT INTO users(username,password_hash,role,doctor_id) VALUES (%s,%s,'doctor',%s)",
                    (f"doctor{i + 1}", hashes["doctor123"], did))

    pids = []
    for _ in range(45):
        cur.execute("""INSERT INTO patient(name,dob,gender,phone,address,blood_group,registered_on)
                       VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING patient_id""",
                    (f"{rnd.choice(FIRST)} {rnd.choice(LAST)}", dt.date(1940, 1, 1) + dt.timedelta(days=rnd.randint(0, 28000)),
                     rnd.choice(["Male", "Female", "Male", "Female", "Other"]), f"97{rnd.randint(10000000, 99999999)}",
                     f"{rnd.randint(1, 99)} Park Street", rnd.choice(BLOOD), today - dt.timedelta(days=rnd.randint(50, 400))))
        pids.append(cur.fetchone()[0])

    med_ids, test_ids = [], []
    for n, p, s in MEDS:
        cur.execute("INSERT INTO medicine(name,unit_price,stock) VALUES (%s,%s,%s) RETURNING medicine_id", (n, p, s))
        med_ids.append(cur.fetchone()[0])
    for n, p in TESTS:
        cur.execute("INSERT INTO lab_test(name,price) VALUES (%s,%s) RETURNING test_id", (n, p))
        test_ids.append(cur.fetchone()[0])

    used = set()

    def pick(lo, hi):
        while True:
            k = (rnd.choice(docs), today + dt.timedelta(days=rnd.randint(lo, hi)), rnd.choice(SLOTS))
            if k not in used:
                used.add(k)
                return k

    for i in range(75):  # past appointments with full clinical + billing history
        did, day, slot = pick(-45, -1)
        pid, status = rnd.choice(pids), ("Cancelled" if i % 10 == 9 else "Completed")
        cur.execute("""INSERT INTO appointment(patient_id,doctor_id,appt_date,slot_time,status,reason)
                       VALUES (%s,%s,%s,%s,%s,%s) RETURNING appointment_id""",
                    (pid, did, day, slot, status, rnd.choice(REASONS)))
        aid = cur.fetchone()[0]
        if status == "Cancelled":
            continue
        when = dt.datetime.combine(day, dt.time.fromisoformat(slot))
        cur.execute("INSERT INTO visit(appointment_id,patient_id,doctor_id,visit_date) VALUES (%s,%s,%s,%s) RETURNING visit_id",
                    (aid, pid, did, when))
        vid = cur.fetchone()[0]
        cur.execute("INSERT INTO diagnosis(visit_id,description,severity) VALUES (%s,%s,%s)", (vid, *rnd.choice(DX)))
        for m in rnd.sample(med_ids, rnd.randint(1, 3)):
            cur.execute("INSERT INTO prescription(visit_id,medicine_id,dosage,days,quantity) VALUES (%s,%s,%s,%s,%s)",
                        (vid, m, rnd.choice(["1-0-1", "1-1-1", "0-0-1", "1-0-0"]), rnd.randint(3, 10), rnd.randint(1, 3)))
        for t in rnd.sample(test_ids, rnd.randint(0, 2)):
            cur.execute("INSERT INTO visit_test(visit_id,test_id,result) VALUES (%s,%s,'Within normal range')", (vid, t))
        cur.execute("CALL sp_generate_bill(%s::int, NULL::int)", (vid,))
        bid = cur.fetchone()[0]
        cur.execute("UPDATE bill SET created_at=%s WHERE bill_id=%s", (when, bid))
        cur.execute("SELECT total_amount FROM bill WHERE bill_id=%s", (bid,))
        total, r = cur.fetchone()[0], rnd.random()
        if r < 0.8:
            amt = total if r < 0.6 else (total / 2).quantize(Decimal("0.01"))
            cur.execute("CALL sp_record_payment(%s::int,%s::numeric,%s)", (bid, amt, rnd.choice(["Cash", "Card", "UPI", "Insurance"])))
            cur.execute("UPDATE payment SET paid_on=%s WHERE bill_id=%s", (when, bid))

    for _ in range(20):  # upcoming bookings
        did, day, slot = pick(0, 12)
        cur.execute("INSERT INTO appointment(patient_id,doctor_id,appt_date,slot_time,reason) VALUES (%s,%s,%s,%s,%s)",
                    (rnd.choice(pids), did, day, slot, rnd.choice(REASONS)))


def main(if_empty=False):
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    if if_empty:
        cur.execute("SELECT to_regclass('public.users')")
        if cur.fetchone()[0]:
            print("Database already initialised.")
            return
    cur.execute(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "db", "schema.sql")).read())
    seed(cur)
    conn.commit()
    conn.close()
    print("Database ready.")


if __name__ == "__main__":
    main("--if-empty" in sys.argv)
