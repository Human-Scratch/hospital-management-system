-- Query catalogue (run after python init_db.py). Section letters match the project checklist.

-- ===== A. BASIC SELECT (10) =====
SELECT * FROM patient ORDER BY registered_on DESC LIMIT 10;                                   -- A1
SELECT name, phone FROM patient WHERE gender = 'Female';                                      -- A2
SELECT name, specialization, consultation_fee FROM doctor ORDER BY consultation_fee DESC;     -- A3
SELECT * FROM appointment WHERE status = 'Booked' AND appt_date >= CURRENT_DATE ORDER BY appt_date, slot_time; -- A4
SELECT name, stock FROM medicine WHERE stock < 150 ORDER BY stock;                            -- A5
SELECT name, price FROM lab_test WHERE price BETWEEN 100 AND 600;                             -- A6
SELECT name FROM patient WHERE name ILIKE 'a%';                                               -- A7
SELECT DISTINCT blood_group FROM patient ORDER BY 1;                                          -- A8
SELECT * FROM bill WHERE status = 'Unpaid';                                                   -- A9
SELECT name, fn_patient_age(dob) AS age FROM patient WHERE fn_patient_age(dob) > 60;          -- A10

-- ===== B. AGGREGATE / GROUP BY (5) =====
SELECT dep.name, COUNT(*) AS appointments FROM appointment a JOIN doctor d ON d.doctor_id = a.doctor_id
  JOIN department dep ON dep.dept_id = d.dept_id GROUP BY dep.name ORDER BY appointments DESC;  -- B1
SELECT blood_group, COUNT(*) AS patients FROM patient GROUP BY blood_group ORDER BY patients DESC; -- B2
SELECT method, COUNT(*) AS payments, SUM(amount) AS collected FROM payment GROUP BY method;   -- B3
SELECT dep.name, ROUND(AVG(d.consultation_fee), 2) AS avg_fee FROM doctor d
  JOIN department dep ON dep.dept_id = d.dept_id GROUP BY dep.name HAVING AVG(d.consultation_fee) > 400; -- B4
SELECT status, COUNT(*) AS bills, SUM(total_amount) AS value FROM bill GROUP BY status;       -- B5

-- ===== C. JOINS (5) =====
SELECT a.appointment_id, p.name AS patient, d.name AS doctor, a.appt_date, a.slot_time
  FROM appointment a JOIN patient p ON p.patient_id = a.patient_id JOIN doctor d ON d.doctor_id = a.doctor_id; -- C1
SELECT v.visit_id, d.name AS doctor, dep.name AS department, v.visit_date
  FROM visit v JOIN doctor d ON d.doctor_id = v.doctor_id JOIN department dep ON dep.dept_id = d.dept_id; -- C2
SELECT pr.visit_id, m.name AS medicine, pr.dosage, pr.quantity, pr.quantity * m.unit_price AS cost
  FROM prescription pr JOIN medicine m ON m.medicine_id = pr.medicine_id;                     -- C3
SELECT p.name FROM patient p LEFT JOIN visit v ON v.patient_id = p.patient_id WHERE v.visit_id IS NULL; -- C4 (never visited)
SELECT b.bill_id, p.name, b.total_amount, COALESCE(SUM(py.amount), 0) AS paid
  FROM bill b JOIN visit v ON v.visit_id = b.visit_id JOIN patient p ON p.patient_id = v.patient_id
  LEFT JOIN payment py ON py.bill_id = b.bill_id GROUP BY b.bill_id, p.name, b.total_amount;  -- C5

-- ===== D. SUBQUERIES (3) =====
SELECT name FROM patient WHERE patient_id IN (
  SELECT v.patient_id FROM visit v JOIN doctor d ON d.doctor_id = v.doctor_id
  JOIN department dep ON dep.dept_id = d.dept_id WHERE dep.name = 'Cardiology');              -- D1
SELECT name, consultation_fee FROM doctor WHERE consultation_fee > (SELECT AVG(consultation_fee) FROM doctor); -- D2
SELECT name FROM medicine WHERE medicine_id NOT IN (SELECT medicine_id FROM prescription);    -- D3 (never prescribed)

-- ===== E. CORRELATED SUBQUERIES (2) =====
SELECT p.name, (SELECT MAX(v.visit_date) FROM visit v WHERE v.patient_id = p.patient_id) AS last_visit
  FROM patient p ORDER BY last_visit DESC NULLS LAST;                                         -- E1
SELECT b.bill_id, v.patient_id, b.total_amount FROM bill b JOIN visit v ON v.visit_id = b.visit_id
  WHERE b.total_amount > (SELECT AVG(b2.total_amount) FROM bill b2 JOIN visit v2 ON v2.visit_id = b2.visit_id
                          WHERE v2.patient_id = v.patient_id);                                -- E2 (above patient's own average)

-- ===== F. DASHBOARD / REPORT QUERIES (5) - the same ones the website runs =====
SELECT dep.name AS department, COUNT(*) AS appointments FROM appointment a JOIN doctor d ON d.doctor_id = a.doctor_id
  JOIN department dep ON dep.dept_id = d.dept_id WHERE a.status <> 'Cancelled' GROUP BY dep.name ORDER BY appointments DESC; -- F1
SELECT TO_CHAR(paid_on, 'YYYY-MM') AS month, SUM(amount) AS revenue FROM payment GROUP BY 1 ORDER BY 1 DESC LIMIT 6;       -- F2
SELECT d.name AS doctor, COUNT(v.visit_id) AS visits FROM doctor d JOIN visit v ON v.doctor_id = d.doctor_id
  GROUP BY d.name ORDER BY visits DESC LIMIT 5;                                               -- F3
SELECT bill_id, patient, balance FROM v_bill_summary WHERE balance > 0 ORDER BY balance DESC LIMIT 5; -- F4
SELECT name, stock FROM medicine WHERE stock < 150 ORDER BY stock LIMIT 5;                    -- F5

-- ===== G. ADVANCED DBMS DEMOS =====
-- Book a slot via stored procedure (second call with same doctor/date/time fails: duplicate slot prevented)
CALL sp_book_appointment(1, 1, CURRENT_DATE + 30, '11:00', 'Check-up', NULL);
CALL sp_book_appointment(2, 1, CURRENT_DATE + 30, '11:00', 'Another patient', NULL);          -- ERROR: Doctor already has an appointment...

-- Transaction demonstration: all-or-nothing prescribing
BEGIN;
  INSERT INTO prescription (visit_id, medicine_id, dosage, days, quantity) VALUES (1, 1, '1-0-1', 5, 10);
  INSERT INTO prescription (visit_id, medicine_id, dosage, days, quantity) VALUES (1, 2, '1-0-1', 5, 999999); -- ERROR: Insufficient stock
ROLLBACK;  -- first insert and its stock deduction are undone too

-- Views
SELECT * FROM v_patient_history WHERE patient_id = 1;
SELECT * FROM v_bill_summary WHERE status <> 'Paid';
