# Hospital Patient & Appointment Management System

Flask + PostgreSQL + Bootstrap. Flow: **User action → Website → Flask backend → SQL/PostgreSQL → database response → Website.**

[![CI](../../actions/workflows/ci.yml/badge.svg)](../../actions)

## Project structure
```
docs/            <- plain HTML/CSS/JS frontend (index.html, app.js, config.js) - no build step
app.py           <- Flask JSON API (/api/...) that also serves docs/
init_db.py       <- creates schema + ~400 sample rows
db/schema.sql    <- tables, indexes, views, functions, procedures, triggers
db/queries.sql   <- all report/demo queries
tests/           <- pytest end-to-end tests (run automatically by GitHub Actions)
render.yaml      <- one-click deploy blueprint
```

## Features
Login/logout (token based) · role-based access (admin, doctor, receptionist) · patient registration (full CRUD) · doctor management ·
appointment booking with live free-slot picker · doctor dashboard (start visit, diagnosis, prescriptions, lab tests) ·
billing & payments · patient history · search / filter / sort · validation with friendly errors · DB-generated dashboard reports · responsive UI.

**Advanced DBMS component - no duplicate slots for a doctor** is enforced in three layers:
1. `sp_book_appointment` locks the doctor row (`FOR UPDATE`) so simultaneous bookings queue up;
2. trigger `trg_prevent_duplicate_slot` raises a readable error;
3. partial unique index `uq_doctor_slot` is the final guarantee (cancelled slots can be re-booked).

## Run locally
```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
createdb hms                                         # or create a DB in pgAdmin
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/hms   # Windows: set DATABASE_URL=...
python init_db.py                                    # schema + sample data
python app.py                                        # open http://127.0.0.1:5000
```
Demo logins: `admin / admin123` · `reception / reception123` · `doctor1...doctor12 / doctor123`

## Upload to GitHub and deploy
```bash
git init && git add . && git commit -m "Hospital HMS" && git branch -M main
git remote add origin https://github.com/<you>/<repo>.git && git push -u origin main
```
**Option A - one deployment (simplest).** On [render.com](https://render.com): New -> Blueprint -> pick the repo. `render.yaml` creates the web service
and PostgreSQL, loads the data on first start, serves the frontend and API from one URL, and redeploys on every push.
(Check Render's current free-tier limits; free instances sleep and free databases may expire.)

**Option B - frontend on GitHub Pages, backend on Render.** Do Option A first, then edit `docs/config.js`:
`window.API_BASE = "https://<your-app>.onrender.com";` commit and push, then on GitHub: Settings -> Pages -> Deploy from branch -> `main` / `docs`.
The Pages URL is your public frontend; it calls the Render API (CORS is enabled; set `CORS_ORIGIN` on Render to your Pages origin to lock it down).
GitHub Pages cannot run Flask or a database, which is why the backend still needs its own host.

Change the demo passwords before showing it publicly.

## Requirement checklist
| Requirement | Where |
|---|---|
| 13 tables (min 8) | `db/schema.sql` |
| 100+ sample records | `init_db.py` (~400 rows) |
| 10 SELECT / 5 GROUP BY / 5 JOIN / 3 subqueries / 2 correlated / 5 dashboard | `db/queries.sql` (sections A–F); dashboard queries also run in `app.py` (`REPORTS`) |
| 3 views | `v_doctor_schedule`, `v_patient_history`, `v_bill_summary` |
| 4 indexes | `uq_doctor_slot`, `idx_appt_doctor_date`, `idx_patient_phone`, `idx_visit_patient` |
| 3 stored procedures | `sp_book_appointment`, `sp_generate_bill`, `sp_record_payment` |
| 2 functions | `fn_bill_total`, `fn_patient_age` |
| 3 triggers | duplicate slot, stock reduction, bill status |
| Transaction demo | prescribing (all-or-nothing) in `app.py`; doctor + login creation; SQL demo in `queries.sql` §G |
| Testing evidence | `tests/test_app.py`, GitHub Actions run (green tick on the repo) |

## ER model
```mermaid
erDiagram
  DEPARTMENT ||--o{ DOCTOR : has
  DOCTOR ||--o| USERS : "logs in as"
  PATIENT ||--o{ APPOINTMENT : books
  DOCTOR ||--o{ APPOINTMENT : "is booked for"
  APPOINTMENT ||--o| VISIT : "results in"
  PATIENT ||--o{ VISIT : has
  DOCTOR ||--o{ VISIT : conducts
  VISIT ||--o{ DIAGNOSIS : has
  VISIT ||--o{ PRESCRIPTION : has
  MEDICINE ||--o{ PRESCRIPTION : "prescribed in"
  VISIT ||--o{ VISIT_TEST : orders
  LAB_TEST ||--o{ VISIT_TEST : "ordered as"
  VISIT ||--o| BILL : generates
  BILL ||--o{ PAYMENT : "settled by"
```
Schema is in 3NF: every non-key column depends only on its table's key; many-to-many links (medicines, tests) go through
`prescription` / `visit_test`. `bill.total_amount` is a deliberate snapshot (computed by `fn_bill_total`) so a bill doesn't change if prices change later.

## Known limitations (mention in your viva)
Login token is kept in browser localStorage (fine for a coursework demo; use HttpOnly cookies + CSRF protection in production); passwords are hashed (scrypt) but there is no password-reset flow; slots are fixed 30-minute blocks 09:00–16:30.
