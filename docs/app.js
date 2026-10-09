// MediCare HMS frontend: plain JavaScript single-page app (hash routing) talking to the Flask JSON API.
(() => {
  const API = (window.API_BASE || "").replace(/\/$/, "");
  const CUR = window.CURRENCY || "$";
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = v => CUR + Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const go = h => { location.hash = h; };
  const view = h => { $("#view").innerHTML = h; };
  const sel = (a, b) => (a === b ? "selected" : "");
  const today = () => new Date().toISOString().slice(0, 10);
  let S = null;
  try { S = JSON.parse(localStorage.getItem("hms")); } catch (e) { /* ignore */ }
  const can = (...r) => !!S && r.includes(S.user.role);

  function toast(msg, type = "success") {
    const el = document.createElement("div");
    el.className = `alert alert-${type} alert-dismissible fade show shadow-sm`;
    el.innerHTML = `${esc(msg)}<button class="btn-close" data-bs-dismiss="alert"></button>`;
    $("#flash").append(el);
    setTimeout(() => el.remove(), 6000);
  }
  const fail = e => toast(e.message, "danger");

  async function api(path, method = "GET", body) {
    let r;
    try {
      r = await fetch(API + "/api" + path, {
        method,
        headers: { "Content-Type": "application/json", ...(S ? { Authorization: "Bearer " + S.token } : {}) },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch (e) { throw new Error("Cannot reach the server. If it was idle, wait a minute and retry."); }
    let data = null;
    try { data = await r.json(); } catch (e) { /* no body */ }
    if (r.status === 401 && S) { logout(); throw new Error("Session expired - please log in again."); }
    if (!r.ok) throw new Error((data && data.error) || "Request failed.");
    return data;
  }

  // ---------- small UI helpers
  const table = (head, rows, empty = "Nothing to show.") =>
    `<div class="table-responsive"><table class="table table-hover table-sm mb-0 align-middle"><thead><tr>${head.map(h => `<th>${h}</th>`).join("")}</tr></thead><tbody>${
      rows.length ? rows.join("") : `<tr><td colspan="${head.length}" class="p-3 text-muted">${empty}</td></tr>`}</tbody></table></div>`;
  const card = (title, inner, cls = "") => `<div class="card shadow-sm h-100 ${cls}"><div class="card-header fw-semibold">${title}</div>${inner}</div>`;
  const badge = s => `<span class="badge bg-${{ Booked: "primary", Completed: "success", Cancelled: "secondary", Paid: "success", Partial: "warning", Unpaid: "danger" }[s] || "secondary"}">${esc(s)}</span>`;
  const apptAction = a => a.status === "Booked"
    ? (can("admin", "doctor") ? `<button class="btn btn-sm btn-success" onclick="HMS.start(${a.appointment_id})">Start visit</button> ` : "") +
      (can("admin", "receptionist") ? `<button class="btn btn-sm btn-outline-danger" onclick="HMS.cancel(${a.appointment_id})">Cancel</button>` : "")
    : a.visit_id ? `<a class="btn btn-sm btn-outline-primary" href="#/visit/${a.visit_id}">Visit</a>` : "";
  const formData = f => Object.fromEntries(new FormData(f));

  function nav() {
    const l = (h, t) => `<a class="btn btn-sm btn-outline-light" href="${h}">${t}</a>`;
    $("#nav").innerHTML = !S ? "" :
      l("#/dashboard", "Dashboard") + l("#/patients", "Patients") + l("#/doctors", "Doctors") + l("#/appointments", "Appointments") +
      (can("admin", "receptionist") ? l("#/billing", "Billing") : "") +
      `<span class="text-white small ms-2">${esc(S.user.name)} <span class="badge bg-light text-primary">${esc(S.user.role)}</span></span>
       <button class="btn btn-sm btn-light" onclick="HMS.logout()">Logout</button>`;
  }
  function logout() { S = null; localStorage.removeItem("hms"); go("#/login"); }

  // ---------- pages
  function pageLogin() {
    view(`<div class="row justify-content-center"><div class="col-md-5 col-lg-4"><div class="card shadow-sm"><div class="card-body p-4">
      <h4 class="mb-3">Sign in</h4>
      <form id="f"><div class="mb-3"><label class="form-label">Username</label><input name="username" class="form-control" required autofocus></div>
      <div class="mb-3"><label class="form-label">Password</label><input name="password" type="password" class="form-control" required></div>
      <button class="btn btn-primary w-100">Login</button></form><hr>
      <p class="small text-muted mb-0">Demo: <code>admin/admin123</code>, <code>reception/reception123</code>, <code>doctor1/doctor123</code></p></div></div></div></div>`);
    $("#f").onsubmit = async e => {
      e.preventDefault();
      try {
        S = await api("/login", "POST", formData(e.target));
        localStorage.setItem("hms", JSON.stringify(S));
        go("#/dashboard");
      } catch (err) { fail(err); }
    };
  }

  async function pageDash() {
    const d = await api("/dashboard"), st = d.stats;
    const cards = [["Patients", st.patients], ["Doctors", st.doctors], ["Today's bookings", st.today], ["Outstanding", money(st.outstanding)]]
      .map(([l, v]) => `<div class="col-6 col-md-3"><div class="card text-center shadow-sm"><div class="card-body"><div class="fs-3 fw-bold text-primary">${v}</div><div class="text-muted small">${l}</div></div></div></div>`).join("");
    const mine = S.user.role === "doctor" ? `<div class="mb-4">${card("My appointments today", table(["Time", "Patient", "Reason", "Status", ""],
      d.mine.map(a => `<tr><td>${a.slot_time}</td><td><a href="#/patients/${a.patient_id}">${esc(a.patient)}</a></td><td>${esc(a.reason)}</td><td>${badge(a.status)}</td><td class="text-end">${apptAction(a)}</td></tr>`), "No appointments today."))}</div>` : "";
    const reps = d.reports.map(r => `<div class="col-md-6">${card(esc(r.title), r.rows.length
      ? table(Object.keys(r.rows[0]).map(k => esc(k.replace(/_/g, " "))), r.rows.map(x => `<tr>${Object.values(x).map(v => `<td>${esc(v)}</td>`).join("")}</tr>`))
      : '<p class="p-3 mb-0 text-muted">No data yet.</p>')}</div>`).join("");
    view(`<h3 class="mb-3">Dashboard</h3><div class="row g-3 mb-4">${cards}</div>${mine}<div class="row g-3">${reps}</div>`);
  }

  async function pagePatients() {
    view(`<div class="d-flex justify-content-between align-items-center mb-3"><h3 class="mb-0">Patients</h3>
      ${can("admin", "receptionist") ? '<a class="btn btn-primary" href="#/patients/new">+ Register patient</a>' : ""}</div>
      <form id="flt" class="row g-2 mb-3">
        <div class="col-md-5"><input name="q" class="form-control" placeholder="Search name or phone"></div>
        <div class="col-6 col-md-2"><select name="gender" class="form-select"><option value="">All genders</option><option>Male</option><option>Female</option><option>Other</option></select></div>
        <div class="col-6 col-md-3"><select name="sort" class="form-select"><option value="name">Name A-Z</option><option value="youngest">Youngest first</option><option value="newest">Recently registered</option></select></div>
        <div class="col-md-2"><button class="btn btn-outline-primary w-100">Apply</button></div></form>
      <div class="card shadow-sm" id="list"></div>`);
    const load = async () => {
      const rows = await api("/patients?" + new URLSearchParams(new FormData($("#flt"))));
      $("#list").innerHTML = table(["#", "Name", "Age", "Gender", "Phone", "Blood", ""], rows.map(p =>
        `<tr><td>${p.patient_id}</td><td><a href="#/patients/${p.patient_id}">${esc(p.name)}</a></td><td>${p.age}</td><td>${esc(p.gender)}</td><td>${esc(p.phone)}</td><td>${esc(p.blood_group || "-")}</td>
         <td class="text-end text-nowrap">${can("admin", "receptionist") ? `<a class="btn btn-sm btn-outline-secondary" href="#/patients/${p.patient_id}/edit">Edit</a>
         <button class="btn btn-sm btn-outline-danger" onclick="HMS.delPatient(${p.patient_id})">Delete</button>` : ""}</td></tr>`), "No patients found.");
    };
    $("#flt").onsubmit = e => { e.preventDefault(); load().catch(fail); };
    await load();
  }

  async function pagePatientForm(id) {
    const p = id ? (await api("/patients/" + id)).patient : {};
    view(`<h3>${id ? "Edit" : "Register"} patient</h3>
      <form id="f" class="card shadow-sm p-4" style="max-width:720px"><div class="row g-3">
        <div class="col-md-6"><label class="form-label">Full name *</label><input name="name" class="form-control" required minlength="2" value="${esc(p.name)}"></div>
        <div class="col-md-3"><label class="form-label">Date of birth *</label><input name="dob" type="date" max="${today()}" class="form-control" required value="${esc(p.dob)}"></div>
        <div class="col-md-3"><label class="form-label">Gender *</label><select name="gender" class="form-select" required>${["Male", "Female", "Other"].map(g => `<option ${sel(g, p.gender)}>${g}</option>`).join("")}</select></div>
        <div class="col-md-6"><label class="form-label">Phone *</label><input name="phone" class="form-control" required pattern="\\+?\\d{7,15}" title="7-15 digits" value="${esc(p.phone)}"></div>
        <div class="col-md-6"><label class="form-label">Blood group</label><select name="blood_group" class="form-select"><option value="">Unknown</option>${["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"].map(b => `<option ${sel(b, p.blood_group)}>${b}</option>`).join("")}</select></div>
        <div class="col-12"><label class="form-label">Address</label><textarea name="address" class="form-control" rows="2">${esc(p.address)}</textarea></div>
      </div><div class="mt-3"><button class="btn btn-primary">Save</button> <a class="btn btn-link" href="#/patients">Cancel</a></div></form>`);
    $("#f").onsubmit = async e => {
      e.preventDefault();
      try {
        const r = id ? await api("/patients/" + id, "PUT", formData(e.target)) : await api("/patients", "POST", formData(e.target));
        toast("Patient saved."); go("#/patients/" + r.patient_id);
      } catch (err) { fail(err); }
    };
  }

  async function pagePatient(id) {
    const d = await api("/patients/" + id), p = d.patient;
    view(`<div class="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-3"><div><h3 class="mb-0">${esc(p.name)}</h3>
      <div class="text-muted">${p.age} yrs &middot; ${esc(p.gender)} &middot; ${esc(p.phone)} &middot; Blood: ${esc(p.blood_group || "-")}</div><div class="small text-muted">${esc(p.address)}</div></div>
      ${can("admin", "receptionist") ? `<a class="btn btn-primary" href="#/book?patient=${p.patient_id}">Book appointment</a>` : ""}</div>
      <div class="mb-4">${card("Medical history", table(["Date", "Doctor", "Diagnosis", "Medicines", "Tests", ""], d.history.map(h =>
        `<tr><td>${esc(h.visit_date.slice(0, 10))}</td><td>${esc(h.doctor)}<div class="small text-muted">${esc(h.department)}</div></td><td>${esc(h.diagnoses || "-")}</td><td>${esc(h.medicines || "-")}</td><td>${esc(h.tests || "-")}</td><td><a href="#/visit/${h.visit_id}">Open</a></td></tr>`), "No visits recorded."))}</div>
      ${card("Appointments", table(["Date", "Time", "Doctor", "Status"], d.appts.map(a => `<tr><td>${a.appt_date}</td><td>${a.slot_time}</td><td>${esc(a.doctor)}</td><td>${badge(a.status)}</td></tr>`), "None."))}`);
  }

  async function pageDoctors() {
    const rows = await api("/doctors");
    view(`<div class="d-flex justify-content-between align-items-center mb-3"><h3 class="mb-0">Doctors</h3>${can("admin") ? '<a class="btn btn-primary" href="#/doctors/new">+ Add doctor</a>' : ""}</div>
      <div class="card shadow-sm">${table(["Name", "Department", "Phone", "Email", "Fee", ""], rows.map(d =>
        `<tr><td>${esc(d.name)}</td><td>${esc(d.department)}</td><td>${esc(d.phone)}</td><td>${esc(d.email)}</td><td>${money(d.consultation_fee)}</td>
         <td class="text-end">${can("admin") ? `<button class="btn btn-sm btn-outline-danger" onclick="HMS.delDoctor(${d.doctor_id})">Delete</button>` : ""}</td></tr>`))}</div>`);
  }

  async function pageDoctorNew() {
    const L = await api("/lookups");
    const inp = (n, l, t = "text", x = "") => `<div class="col-md-6"><label class="form-label">${l}</label><input name="${n}" type="${t}" class="form-control" ${x}></div>`;
    view(`<h3>Add doctor</h3><form id="f" class="card shadow-sm p-4" style="max-width:720px"><div class="row g-3">
      ${inp("name", "Name *", "text", "required")}
      <div class="col-md-6"><label class="form-label">Department *</label><select name="dept_id" class="form-select" required>${L.departments.map(d => `<option value="${d.dept_id}">${esc(d.name)}</option>`).join("")}</select></div>
      ${inp("specialization", "Specialization")}${inp("phone", "Phone")}${inp("email", "Email *", "email", "required")}${inp("fee", "Consultation fee *", "number", 'required min="0" step="0.01"')}
      ${inp("username", "Login username *", "text", "required")}${inp("password", "Login password * (min 6)", "password", 'required minlength="6"')}
      </div><div class="mt-3"><button class="btn btn-primary">Create</button> <a class="btn btn-link" href="#/doctors">Cancel</a></div></form>`);
    $("#f").onsubmit = async e => {
      e.preventDefault();
      try { await api("/doctors", "POST", formData(e.target)); toast("Doctor and login account created."); go("#/doctors"); } catch (err) { fail(err); }
    };
  }

  async function pageAppts() {
    const docs = S.user.role === "doctor" ? [] : (await api("/lookups")).doctors;
    view(`<div class="d-flex justify-content-between align-items-center mb-3"><h3 class="mb-0">Appointments</h3>${can("admin", "receptionist") ? '<a class="btn btn-primary" href="#/book">+ Book appointment</a>' : ""}</div>
      <form id="flt" class="row g-2 mb-3"><div class="col-6 col-md-3"><input type="date" name="date" class="form-control"></div>
        ${docs.length ? `<div class="col-6 col-md-3"><select name="doctor_id" class="form-select"><option value="">All doctors</option>${docs.map(d => `<option value="${d.doctor_id}">${esc(d.name)}</option>`).join("")}</select></div>` : ""}
        <div class="col-6 col-md-2"><select name="status" class="form-select"><option value="">Any status</option><option>Booked</option><option>Completed</option><option>Cancelled</option></select></div>
        <div class="col-6 col-md-2"><select name="sort" class="form-select"><option value="newest">Newest first</option><option value="oldest">Oldest first</option></select></div>
        <div class="col-md-2"><button class="btn btn-outline-primary w-100">Filter</button></div></form><div class="card shadow-sm" id="list"></div>`);
    const load = async () => {
      const rows = await api("/appointments?" + new URLSearchParams(new FormData($("#flt"))));
      $("#list").innerHTML = table(["Date", "Time", "Patient", "Doctor", "Reason", "Status", ""], rows.map(a =>
        `<tr><td>${a.appt_date}</td><td>${a.slot_time}</td><td><a href="#/patients/${a.patient_id}">${esc(a.patient)}</a></td><td>${esc(a.doctor)}</td><td>${esc(a.reason)}</td><td>${badge(a.status)}</td><td class="text-end text-nowrap">${apptAction(a)}</td></tr>`), "No appointments match.");
    };
    $("#flt").onsubmit = e => { e.preventDefault(); load().catch(fail); };
    await load();
  }

  async function pageBook(patientId) {
    const L = await api("/lookups");
    view(`<h3>Book appointment</h3><form id="f" class="card shadow-sm p-4" style="max-width:720px"><div class="row g-3">
      <div class="col-md-6"><label class="form-label">Patient *</label><select name="patient_id" class="form-select" required><option value="">Choose...</option>${L.patients.map(p => `<option value="${p.patient_id}" ${sel(String(p.patient_id), patientId)}>${esc(p.name)} (${esc(p.phone)})</option>`).join("")}</select></div>
      <div class="col-md-6"><label class="form-label">Doctor *</label><select name="doctor_id" id="doc" class="form-select" required><option value="">Choose...</option>${L.doctors.map(d => `<option value="${d.doctor_id}">${esc(d.name)} - ${esc(d.specialization)}</option>`).join("")}</select></div>
      <div class="col-md-6"><label class="form-label">Date *</label><input type="date" name="appt_date" id="day" min="${today()}" class="form-control" required></div>
      <div class="col-md-6"><label class="form-label">Available slot *</label><select name="slot_time" id="slot" class="form-select" required><option value="">Pick doctor and date first</option></select></div>
      <div class="col-12"><label class="form-label">Reason</label><input name="reason" maxlength="200" class="form-control"></div>
      </div><div class="mt-3"><button class="btn btn-primary">Confirm booking</button> <a class="btn btn-link" href="#/appointments">Cancel</a></div></form>`);
    const loadSlots = async () => {
      if (!$("#doc").value || !$("#day").value) return;
      try {
        const free = await api(`/slots?doctor_id=${$("#doc").value}&date=${$("#day").value}`);
        $("#slot").innerHTML = free.length ? free.map(t => `<option>${t}</option>`).join("") : '<option value="">No free slots that day</option>';
      } catch (e) { fail(e); }
    };
    $("#doc").onchange = loadSlots; $("#day").onchange = loadSlots;
    $("#f").onsubmit = async e => {
      e.preventDefault();
      try { const r = await api("/appointments", "POST", formData(e.target)); toast(`Appointment #${r.appointment_id} confirmed.`); go("#/appointments"); } catch (err) { fail(err); }
    };
  }

  async function pageVisit(id) {
    const d = await api("/visits/" + id), v = d.visit, E = d.can_edit;
    const post = (path, body, msg) => api(`/visits/${id}${path}`, "POST", body).then(() => { toast(msg); route(); }).catch(fail);
    view(`<div class="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-3"><div><h3 class="mb-0">Visit #${v.visit_id}</h3>
      <div class="text-muted"><a href="#/patients/${v.patient_id}">${esc(v.patient)}</a> (${v.age} yrs) &middot; ${esc(v.doctor)} &middot; ${esc(v.visit_date.replace("T", " "))}</div></div>
      ${can("admin", "receptionist") ? `<button class="btn btn-warning" id="bill">${v.bill_id ? "Recalculate bill" : "Generate bill"}</button>` : ""}</div>
      <div class="row g-3">
        <div class="col-lg-6">${card("Diagnosis", `<ul class="list-group list-group-flush">${d.dx.map(x => `<li class="list-group-item">${esc(x.description)} <span class="badge bg-secondary">${esc(x.severity)}</span></li>`).join("") || '<li class="list-group-item text-muted">None yet.</li>'}</ul>
          ${E ? `<form id="fdx" class="card-body row g-2 border-top"><div class="col-7"><input name="description" class="form-control" placeholder="Diagnosis" required maxlength="200"></div>
          <div class="col-3"><select name="severity" class="form-select"><option>Mild</option><option>Moderate</option><option>Severe</option></select></div><div class="col-2"><button class="btn btn-primary w-100">Add</button></div></form>` : ""}`)}</div>
        <div class="col-lg-6">${card("Lab tests", `<ul class="list-group list-group-flush">${d.tests.map(t => `<li class="list-group-item"><div class="d-flex justify-content-between"><span>${esc(t.name)}</span><span class="text-muted">${money(t.price)}</span></div>
          ${E ? `<form class="fres input-group input-group-sm mt-1" data-tid="${t.visit_test_id}"><input name="result" class="form-control" placeholder="Result" value="${esc(t.result)}"><button class="btn btn-outline-primary">Save</button></form>` : `<div class="small text-muted">${esc(t.result || "Pending")}</div>`}</li>`).join("") || '<li class="list-group-item text-muted">None ordered.</li>'}</ul>
          ${E ? `<form id="ftest" class="card-body row g-2 border-top"><div class="col-9"><select name="test_id" class="form-select">${d.labs.map(l => `<option value="${l.test_id}">${esc(l.name)} (${money(l.price)})</option>`).join("")}</select></div><div class="col-3"><button class="btn btn-primary w-100">Order</button></div></form>` : ""}`)}</div>
        <div class="col-12">${card("Prescription", table(["Medicine", "Dosage", "Days", "Qty", "Cost"], d.rx.map(r => `<tr><td>${esc(r.medicine)}</td><td>${esc(r.dosage)}</td><td>${r.days}</td><td>${r.quantity}</td><td>${money(r.cost)}</td></tr>`), "Nothing prescribed.") +
          (E ? `<form id="frx" class="card-body border-top"><div class="small text-muted mb-2">Fill one or more rows. All rows are saved together, or none if any fails (e.g. insufficient stock).</div>
          ${[0, 1, 2].map(() => `<div class="row g-2 mb-2 rx-row"><div class="col-md-5"><select name="m" class="form-select"><option value="">- medicine -</option>${d.meds.map(m => `<option value="${m.medicine_id}">${esc(m.name)} (stock ${m.stock})</option>`).join("")}</select></div>
          <div class="col-md-3"><input name="d" class="form-control" placeholder="Dosage e.g. 1-0-1"></div><div class="col-6 col-md-2"><input name="n" type="number" min="1" class="form-control" placeholder="Days"></div><div class="col-6 col-md-2"><input name="q" type="number" min="1" class="form-control" placeholder="Qty"></div></div>`).join("")}
          <button class="btn btn-primary">Save prescription</button></form>` : ""))}</div></div>
      ${v.bill_id && can("admin", "receptionist") ? `<p class="mt-3"><a href="#/billing/${v.bill_id}">View bill &rarr;</a></p>` : ""}`);
    if ($("#bill")) $("#bill").onclick = () => api(`/visits/${id}/bill`, "POST").then(r => go("#/billing/" + r.bill_id)).catch(fail);
    if (!E) return;
    $("#fdx").onsubmit = e => { e.preventDefault(); post("/diagnosis", formData(e.target), "Diagnosis added."); };
    $("#ftest").onsubmit = e => { e.preventDefault(); post("/tests", formData(e.target), "Lab test ordered."); };
    document.querySelectorAll(".fres").forEach(f => { f.onsubmit = e => { e.preventDefault(); post(`/tests/${f.dataset.tid}/result`, formData(f), "Result saved."); }; });
    $("#frx").onsubmit = e => {
      e.preventDefault();
      const items = [...document.querySelectorAll(".rx-row")].map(r => ({ medicine_id: r.querySelector("[name=m]").value, dosage: r.querySelector("[name=d]").value, days: r.querySelector("[name=n]").value, quantity: r.querySelector("[name=q]").value })).filter(i => i.medicine_id && i.quantity);
      post("/prescribe", { items }, "Medicines prescribed and stock updated.");
    };
  }

  async function pageBills() {
    view(`<h3>Billing</h3><form id="flt" class="row g-2 mb-3"><div class="col-6 col-md-3"><select name="status" class="form-select"><option value="">Any status</option><option>Unpaid</option><option>Partial</option><option>Paid</option></select></div>
      <div class="col-6 col-md-3"><select name="sort" class="form-select"><option value="newest">Newest first</option><option value="balance">Highest balance</option><option value="patient">Patient A-Z</option></select></div>
      <div class="col-md-2"><button class="btn btn-outline-primary w-100">Apply</button></div></form><div class="card shadow-sm" id="list"></div>`);
    const load = async () => {
      const rows = await api("/bills?" + new URLSearchParams(new FormData($("#flt"))));
      $("#list").innerHTML = table(["Bill", "Patient", "Total", "Paid", "Balance", "Status", ""], rows.map(b =>
        `<tr><td>#${b.bill_id}</td><td>${esc(b.patient)}</td><td>${money(b.total_amount)}</td><td>${money(b.paid)}</td><td>${money(b.balance)}</td><td>${badge(b.status)}</td><td class="text-end"><a class="btn btn-sm btn-outline-primary" href="#/billing/${b.bill_id}">Open</a></td></tr>`), "No bills.");
    };
    $("#flt").onsubmit = e => { e.preventDefault(); load().catch(fail); };
    await load();
  }

  async function pageBill(id) {
    const d = await api("/bills/" + id), b = d.bill;
    view(`<h3>Bill #${b.bill_id} ${badge(b.status)}</h3><p class="text-muted"><a href="#/patients/${b.patient_id}">${esc(b.patient)}</a> &middot; <a href="#/visit/${b.visit_id}">Visit #${b.visit_id}</a></p>
      <div class="row g-3"><div class="col-lg-7">${card("Items", table(["Item", "Qty", "Amount"], d.items.map(i => `<tr><td>${esc(i.item)}</td><td>${i.qty}</td><td>${money(i.amount)}</td></tr>`)) +
        `<table class="table table-sm mb-0"><tr><th>Total</th><td class="text-end">${money(b.total_amount)}</td></tr><tr><td>Paid</td><td class="text-end">${money(b.paid)}</td></tr><tr><th>Balance due</th><th class="text-end">${money(b.balance)}</th></tr></table>`)}</div>
        <div class="col-lg-5"><div class="mb-3">${card("Payments", `<ul class="list-group list-group-flush">${d.payments.map(p => `<li class="list-group-item d-flex justify-content-between"><span>${esc(p.paid_on.slice(0, 10))} &middot; ${esc(p.method)}</span><span>${money(p.amount)}</span></li>`).join("") || '<li class="list-group-item text-muted">No payments yet.</li>'}</ul>`)}</div>
        ${b.balance > 0 ? `<form id="fpay" class="card shadow-sm p-3"><div class="row g-2"><div class="col-6"><input name="amount" type="number" step="0.01" min="0.01" max="${b.balance}" class="form-control" placeholder="Amount" required></div>
        <div class="col-6"><select name="method" class="form-select"><option>Cash</option><option>Card</option><option>UPI</option><option>Insurance</option></select></div><div class="col-12"><button class="btn btn-success w-100">Record payment</button></div></div></form>` : ""}</div></div>`);
    if ($("#fpay")) $("#fpay").onsubmit = async e => {
      e.preventDefault();
      try { await api(`/bills/${id}/pay`, "POST", formData(e.target)); toast("Payment recorded."); route(); } catch (err) { fail(err); }
    };
  }

  // ---------- actions used by inline onclick handlers
  window.HMS = {
    logout,
    start: id => api(`/appointments/${id}/start`, "POST").then(r => go("#/visit/" + r.visit_id)).catch(fail),
    cancel: id => confirm("Cancel this appointment?") && api(`/appointments/${id}/cancel`, "POST").then(() => { toast("Appointment cancelled; the slot is free again.", "info"); route(); }).catch(fail),
    delPatient: id => confirm("Delete this patient?") && api("/patients/" + id, "DELETE").then(() => { toast("Patient deleted.", "info"); route(); }).catch(fail),
    delDoctor: id => confirm("Delete this doctor?") && api("/doctors/" + id, "DELETE").then(() => { toast("Doctor deleted.", "info"); route(); }).catch(fail),
  };

  // ---------- router
  const R = [
    [/^#\/login$/, pageLogin], [/^#\/dashboard$/, pageDash], [/^#\/patients$/, pagePatients],
    [/^#\/patients\/new$/, () => pagePatientForm()], [/^#\/patients\/(\d+)\/edit$/, pagePatientForm], [/^#\/patients\/(\d+)$/, pagePatient],
    [/^#\/doctors$/, pageDoctors], [/^#\/doctors\/new$/, pageDoctorNew], [/^#\/appointments$/, pageAppts],
    [/^#\/book(?:\?patient=(\d+))?$/, pageBook], [/^#\/visit\/(\d+)$/, pageVisit], [/^#\/billing$/, pageBills], [/^#\/billing\/(\d+)$/, pageBill],
  ];
  async function route() {
    const h = location.hash || "#/dashboard";
    if (!S && h !== "#/login") return go("#/login");
    if (S && h === "#/login") return go("#/dashboard");
    nav();
    for (const [re, fn] of R) {
      const m = h.match(re);
      if (m) { try { await fn(...m.slice(1)); } catch (e) { fail(e); } return; }
    }
    view('<div class="text-center py-5"><h3>Page not found</h3><a href="#/dashboard">Back to dashboard</a></div>');
  }
  window.addEventListener("hashchange", route);
  route();
})();
