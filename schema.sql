-- Hospital Patient & Appointment Management System (PostgreSQL 14+)
DROP TABLE IF EXISTS payment, bill, visit_test, lab_test, prescription, medicine,
  diagnosis, visit, appointment, users, doctor, department, patient CASCADE;

-- ===================== TABLES (13) =====================
CREATE TABLE department (
  dept_id SERIAL PRIMARY KEY,
  name VARCHAR(60) NOT NULL UNIQUE);

CREATE TABLE doctor (
  doctor_id SERIAL PRIMARY KEY,
  name VARCHAR(80) NOT NULL,
  dept_id INT NOT NULL REFERENCES department(dept_id),
  specialization VARCHAR(80),
  phone VARCHAR(20),
  email VARCHAR(100) UNIQUE,
  consultation_fee NUMERIC(8,2) NOT NULL CHECK (consultation_fee >= 0));

CREATE TABLE users (
  user_id SERIAL PRIMARY KEY,
  username VARCHAR(50) NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role VARCHAR(15) NOT NULL CHECK (role IN ('admin','doctor','receptionist')),
  doctor_id INT REFERENCES doctor(doctor_id) ON DELETE CASCADE);

CREATE TABLE patient (
  patient_id SERIAL PRIMARY KEY,
  name VARCHAR(80) NOT NULL,
  dob DATE NOT NULL,
  gender VARCHAR(10) NOT NULL CHECK (gender IN ('Male','Female','Other')),
  phone VARCHAR(20) NOT NULL,
  address TEXT,
  blood_group VARCHAR(3),
  registered_on DATE NOT NULL DEFAULT CURRENT_DATE);

CREATE TABLE appointment (
  appointment_id SERIAL PRIMARY KEY,
  patient_id INT NOT NULL REFERENCES patient(patient_id),
  doctor_id INT NOT NULL REFERENCES doctor(doctor_id),
  appt_date DATE NOT NULL,
  slot_time TIME NOT NULL,
  status VARCHAR(12) NOT NULL DEFAULT 'Booked' CHECK (status IN ('Booked','Completed','Cancelled')),
  reason VARCHAR(200),
  created_at TIMESTAMP NOT NULL DEFAULT now());

CREATE TABLE visit (
  visit_id SERIAL PRIMARY KEY,
  appointment_id INT UNIQUE REFERENCES appointment(appointment_id),
  patient_id INT NOT NULL REFERENCES patient(patient_id),
  doctor_id INT NOT NULL REFERENCES doctor(doctor_id),
  visit_date TIMESTAMP NOT NULL DEFAULT now(),
  notes TEXT);

CREATE TABLE diagnosis (
  diagnosis_id SERIAL PRIMARY KEY,
  visit_id INT NOT NULL REFERENCES visit(visit_id) ON DELETE CASCADE,
  description VARCHAR(200) NOT NULL,
  severity VARCHAR(10) NOT NULL DEFAULT 'Mild' CHECK (severity IN ('Mild','Moderate','Severe')));

CREATE TABLE medicine (
  medicine_id SERIAL PRIMARY KEY,
  name VARCHAR(80) NOT NULL UNIQUE,
  unit_price NUMERIC(8,2) NOT NULL CHECK (unit_price >= 0),
  stock INT NOT NULL CHECK (stock >= 0));

CREATE TABLE prescription (
  prescription_id SERIAL PRIMARY KEY,
  visit_id INT NOT NULL REFERENCES visit(visit_id) ON DELETE CASCADE,
  medicine_id INT NOT NULL REFERENCES medicine(medicine_id),
  dosage VARCHAR(60) NOT NULL,
  days INT NOT NULL CHECK (days > 0),
  quantity INT NOT NULL CHECK (quantity > 0));

CREATE TABLE lab_test (
  test_id SERIAL PRIMARY KEY,
  name VARCHAR(80) NOT NULL UNIQUE,
  price NUMERIC(8,2) NOT NULL CHECK (price >= 0));

CREATE TABLE visit_test (
  visit_test_id SERIAL PRIMARY KEY,
  visit_id INT NOT NULL REFERENCES visit(visit_id) ON DELETE CASCADE,
  test_id INT NOT NULL REFERENCES lab_test(test_id),
  result TEXT,
  ordered_on TIMESTAMP NOT NULL DEFAULT now());

CREATE TABLE bill (
  bill_id SERIAL PRIMARY KEY,
  visit_id INT NOT NULL UNIQUE REFERENCES visit(visit_id) ON DELETE CASCADE,
  total_amount NUMERIC(10,2) NOT NULL CHECK (total_amount >= 0),
  status VARCHAR(10) NOT NULL DEFAULT 'Unpaid' CHECK (status IN ('Unpaid','Partial','Paid')),
  created_at TIMESTAMP NOT NULL DEFAULT now());

CREATE TABLE payment (
  payment_id SERIAL PRIMARY KEY,
  bill_id INT NOT NULL REFERENCES bill(bill_id) ON DELETE CASCADE,
  amount NUMERIC(10,2) NOT NULL CHECK (amount > 0),
  method VARCHAR(12) NOT NULL CHECK (method IN ('Cash','Card','UPI','Insurance')),
  paid_on TIMESTAMP NOT NULL DEFAULT now());

-- ===================== INDEXES =====================
-- Advanced component: DB-level guarantee of no duplicate slot per doctor
CREATE UNIQUE INDEX uq_doctor_slot ON appointment (doctor_id, appt_date, slot_time) WHERE status <> 'Cancelled';
CREATE INDEX idx_appt_doctor_date ON appointment (doctor_id, appt_date);
CREATE INDEX idx_patient_phone ON patient (phone);
CREATE INDEX idx_visit_patient ON visit (patient_id);

-- ===================== FUNCTIONS =====================
CREATE OR REPLACE FUNCTION fn_patient_age(p_dob DATE) RETURNS INT AS $$
  SELECT EXTRACT(YEAR FROM age(CURRENT_DATE, p_dob))::INT
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION fn_bill_total(p_visit INT) RETURNS NUMERIC AS $$
  SELECT COALESCE((SELECT d.consultation_fee FROM visit v JOIN doctor d ON d.doctor_id = v.doctor_id WHERE v.visit_id = p_visit), 0)
       + COALESCE((SELECT SUM(pr.quantity * m.unit_price) FROM prescription pr JOIN medicine m ON m.medicine_id = pr.medicine_id WHERE pr.visit_id = p_visit), 0)
       + COALESCE((SELECT SUM(t.price) FROM visit_test vt JOIN lab_test t ON t.test_id = vt.test_id WHERE vt.visit_id = p_visit), 0)
$$ LANGUAGE sql STABLE;

-- ===================== TRIGGERS =====================
-- 1) Block duplicate appointment slot for the same doctor (friendly message)
CREATE OR REPLACE FUNCTION trg_fn_prevent_duplicate_slot() RETURNS trigger AS $$
BEGIN
  IF NEW.status <> 'Cancelled' AND EXISTS (
       SELECT 1 FROM appointment
       WHERE doctor_id = NEW.doctor_id AND appt_date = NEW.appt_date AND slot_time = NEW.slot_time
         AND status <> 'Cancelled' AND appointment_id IS DISTINCT FROM NEW.appointment_id) THEN
    RAISE EXCEPTION 'Doctor already has an appointment at % on % - please pick another slot.',
      to_char(NEW.slot_time, 'HH24:MI'), NEW.appt_date;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_prevent_duplicate_slot
  BEFORE INSERT OR UPDATE OF doctor_id, appt_date, slot_time, status ON appointment
  FOR EACH ROW EXECUTE FUNCTION trg_fn_prevent_duplicate_slot();

-- 2) Reduce medicine stock when prescribed (rejects if insufficient)
CREATE OR REPLACE FUNCTION trg_fn_reduce_stock() RETURNS trigger AS $$
DECLARE s INT;
BEGIN
  SELECT stock INTO s FROM medicine WHERE medicine_id = NEW.medicine_id FOR UPDATE;
  IF s < NEW.quantity THEN
    RAISE EXCEPTION 'Insufficient stock: only % unit(s) available.', s;
  END IF;
  UPDATE medicine SET stock = stock - NEW.quantity WHERE medicine_id = NEW.medicine_id;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_reduce_stock BEFORE INSERT ON prescription
  FOR EACH ROW EXECUTE FUNCTION trg_fn_reduce_stock();

-- 3) Keep bill status in sync with payments
CREATE OR REPLACE FUNCTION trg_fn_bill_status() RETURNS trigger AS $$
BEGIN
  UPDATE bill SET status = CASE
      WHEN (SELECT SUM(amount) FROM payment WHERE bill_id = NEW.bill_id) >= total_amount THEN 'Paid'
      ELSE 'Partial' END
  WHERE bill_id = NEW.bill_id;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_bill_status AFTER INSERT ON payment
  FOR EACH ROW EXECUTE FUNCTION trg_fn_bill_status();

-- ===================== STORED PROCEDURES =====================
-- Booking: locks the doctor row so concurrent bookings are serialised,
-- then the trigger + partial unique index guard the slot.
CREATE OR REPLACE PROCEDURE sp_book_appointment(
  p_patient INT, p_doctor INT, p_date DATE, p_time TIME, p_reason TEXT, INOUT p_id INT DEFAULT NULL)
LANGUAGE plpgsql AS $$
BEGIN
  IF p_date < CURRENT_DATE THEN RAISE EXCEPTION 'Cannot book an appointment in the past.'; END IF;
  IF p_time < TIME '09:00' OR p_time > TIME '16:30' THEN
    RAISE EXCEPTION 'Slots are available between 09:00 and 16:30.'; END IF;
  PERFORM 1 FROM doctor WHERE doctor_id = p_doctor FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Doctor not found.'; END IF;
  INSERT INTO appointment (patient_id, doctor_id, appt_date, slot_time, reason)
  VALUES (p_patient, p_doctor, p_date, p_time, p_reason)
  RETURNING appointment_id INTO p_id;
END $$;

CREATE OR REPLACE PROCEDURE sp_generate_bill(p_visit INT, INOUT p_bill INT DEFAULT NULL)
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM visit WHERE visit_id = p_visit) THEN
    RAISE EXCEPTION 'Visit not found.'; END IF;
  INSERT INTO bill (visit_id, total_amount) VALUES (p_visit, fn_bill_total(p_visit))
  ON CONFLICT (visit_id) DO UPDATE SET total_amount = EXCLUDED.total_amount WHERE bill.status <> 'Paid'
  RETURNING bill_id INTO p_bill;
  IF p_bill IS NULL THEN SELECT bill_id INTO p_bill FROM bill WHERE visit_id = p_visit; END IF;
END $$;

CREATE OR REPLACE PROCEDURE sp_record_payment(p_bill INT, p_amount NUMERIC, p_method TEXT)
LANGUAGE plpgsql AS $$
DECLARE v_total NUMERIC; v_paid NUMERIC;
BEGIN
  SELECT total_amount INTO v_total FROM bill WHERE bill_id = p_bill FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Bill not found.'; END IF;
  IF p_amount <= 0 THEN RAISE EXCEPTION 'Payment amount must be positive.'; END IF;
  SELECT COALESCE(SUM(amount), 0) INTO v_paid FROM payment WHERE bill_id = p_bill;
  IF v_paid + p_amount > v_total THEN
    RAISE EXCEPTION 'Payment exceeds the balance due (%).', v_total - v_paid; END IF;
  INSERT INTO payment (bill_id, amount, method) VALUES (p_bill, p_amount, p_method);
END $$;

-- ===================== VIEWS =====================
CREATE OR REPLACE VIEW v_doctor_schedule AS
SELECT a.appointment_id, a.doctor_id, d.name AS doctor, a.appt_date, a.slot_time,
       p.patient_id, p.name AS patient, a.status, a.reason, v.visit_id
FROM appointment a
JOIN doctor d ON d.doctor_id = a.doctor_id
JOIN patient p ON p.patient_id = a.patient_id
LEFT JOIN visit v ON v.appointment_id = a.appointment_id;

CREATE OR REPLACE VIEW v_patient_history AS
SELECT v.visit_id, v.patient_id, v.visit_date, d.name AS doctor, dep.name AS department,
  (SELECT string_agg(g.description, '; ') FROM diagnosis g WHERE g.visit_id = v.visit_id) AS diagnoses,
  (SELECT string_agg(m.name || ' (' || pr.dosage || ')', ', ')
     FROM prescription pr JOIN medicine m ON m.medicine_id = pr.medicine_id WHERE pr.visit_id = v.visit_id) AS medicines,
  (SELECT string_agg(t.name, ', ')
     FROM visit_test vt JOIN lab_test t ON t.test_id = vt.test_id WHERE vt.visit_id = v.visit_id) AS tests
FROM visit v
JOIN doctor d ON d.doctor_id = v.doctor_id
JOIN department dep ON dep.dept_id = d.dept_id;

CREATE OR REPLACE VIEW v_bill_summary AS
SELECT b.bill_id, b.visit_id, p.patient_id, p.name AS patient, b.total_amount,
       COALESCE(SUM(py.amount), 0) AS paid,
       b.total_amount - COALESCE(SUM(py.amount), 0) AS balance,
       b.status, b.created_at
FROM bill b
JOIN visit v ON v.visit_id = b.visit_id
JOIN patient p ON p.patient_id = v.patient_id
LEFT JOIN payment py ON py.bill_id = b.bill_id
GROUP BY b.bill_id, p.patient_id, p.name;
