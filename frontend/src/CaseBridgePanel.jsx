import React, { useCallback, useEffect, useState } from 'react'

const initial = { reference: '', kind: 'hit_and_run', priority: 'urgent', plate_query: '', query_mode: 'exact',
  vehicle_description: '', incident_latitude: '23.0225', incident_longitude: '72.5714',
  incident_utc: '', search_until_utc: '', lead_department: '' }

function stamp(value) { return value ? new Date(value).toLocaleString() : 'Not recorded' }

export default function CaseBridgePanel({ api, csrf, cameras, role, department }) {
  const [form, setForm] = useState(initial)
  const [cases, setCases] = useState([])
  const [selectedId, setSelectedId] = useState('')
  const [detail, setDetail] = useState(null)
  const [briefing, setBriefing] = useState(null)
  const [inbox, setInbox] = useState([])
  const [recipient, setRecipient] = useState('')
  const [handoffNote, setHandoffNote] = useState('Please review this confirmed vehicle sighting and check the next available camera.')
  const [note, setNote] = useState('')
  const [message, setMessage] = useState('')
  const [formMessage, setFormMessage] = useState('')
  const [formError, setFormError] = useState(false)
  const [busy, setBusy] = useState(false)
  const [snapshot, setSnapshot] = useState(null)
  const isOperator = role === 'operator'

  const refresh = useCallback(async (id = selectedId) => {
    try {
      if (isOperator) {
        const [list, shift] = await Promise.all([api('/cases'), api('/cases/shift-briefing')])
        setCases(list); setBriefing(shift)
        if (id) setDetail(await api(`/cases/${encodeURIComponent(id)}`))
      } else setInbox(await api('/cases/inbox'))
    } catch (cause) { setMessage(cause.message) }
  }, [api, isOperator, selectedId])

  useEffect(() => { refresh() }, [])

  async function action(task, success) {
    setBusy(true); setMessage('')
    try { await task(); setMessage(success); await refresh() }
    catch (cause) { setMessage(cause.message) }
    finally { setBusy(false) }
  }

  async function create(event) {
    event.preventDefault()
    setBusy(true); setMessage(''); setFormError(false); setFormMessage('Opening case…')
    try {
      const item = await api('/cases', { method: 'POST', headers: { 'X-CSRF-Token': csrf },
        signal: AbortSignal.timeout(25000),
        body: JSON.stringify({ ...form, incident_latitude: Number(form.incident_latitude),
          incident_longitude: Number(form.incident_longitude),
          incident_utc: new Date(form.incident_utc).toISOString(),
          search_until_utc: form.search_until_utc ? new Date(form.search_until_utc).toISOString() : null }) })
      setSelectedId(item.id); setForm(initial)
      setFormMessage(`Case ${item.reference} opened. It is listed in the shift briefing; details appear below.`)
      await refresh(item.id)
    } catch (cause) {
      setFormError(true)
      setFormMessage(cause.name === 'TimeoutError' || cause.name === 'AbortError'
        ? 'The server did not respond within 25 seconds. Refresh the briefing before retrying, because the case may have been created.'
        : `Could not open case: ${cause.message}`)
    }
    finally { setBusy(false) }
  }

  async function choose(id) {
    setSelectedId(id); setSnapshot(null)
    try { setDetail(await api(`/cases/${encodeURIComponent(id)}`)) }
    catch (cause) { setMessage(cause.message) }
  }

  async function handoff(sightingId) {
    if (!recipient) { setMessage('Choose a recipient department.'); return }
    await action(() => api(`/cases/${selectedId}/handoffs`, { method: 'POST',
      headers: { 'X-CSRF-Token': csrf },
      body: JSON.stringify({ recipient_department: recipient, sighting_id: sightingId, note: handoffNote }) }),
    'Internal handoff queued. The recipient must acknowledge it from their department sign-in.')
  }

  async function pursue(sightingId) {
    await action(() => api(`/cases/${selectedId}/pursuit?sighting_id=${encodeURIComponent(sightingId)}`,
      { method: 'POST', headers: { 'X-CSRF-Token': csrf } }),
    'Case linked to the existing pursuit engine. Start measured scheduling in the Journey panel after a real capacity benchmark.')
  }

  async function sign() {
    setBusy(true); setMessage('')
    try {
      const result = await api(`/cases/${selectedId}/timeline`,
        { method: 'POST', headers: { 'X-CSRF-Token': csrf } })
      setSnapshot(result); setMessage('Immutable case-timeline snapshot signed.')
      await refresh()
    } catch (cause) { setMessage(cause.message) }
    finally { setBusy(false) }
  }

  async function addRepresentativeWatchlist() {
    await action(() => api('/watchlist', { method: 'POST', headers: { 'X-CSRF-Token': csrf },
      body: JSON.stringify({ plate: detail.case.plate_query, category: 'representative',
        source_label: `CaseBridge demo ${detail.case.reference}`.slice(0, 120) }) }),
    'Representative case watchlist added. This is not an official police database entry.')
  }

  async function startMeasuredPursuit() {
    await action(() => api(`/pursuits/${detail.case.pursuit_id}/schedule`,
      { method: 'POST', headers: { 'X-CSRF-Token': csrf } }),
    'Measured pursuit schedule started. Inspect allocations and coverage in the Journey panel.')
  }

  function downloadSnapshot() {
    if (!snapshot) return
    const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a'); link.href = url
    link.download = `SakhyaPath_Case_${detail.case.reference}_timeline.json`; link.click()
    URL.revokeObjectURL(url)
  }

  const departments = [...new Set(cameras.map(camera => camera.department))].sort()
  return <section className="casebridge" id="casebridge">
    <div className="intelligence-heading"><div><span className="eyebrow">POLICE WORKFLOW / CASEBRIDGE</span>
      <h2>From sighting to action<span>.</span></h2>
      <p>Incident triage, camera gaps, internal district handoff, and an auditable shift record.</p></div>
      <span className="panel-tag">INTERNAL CASE INBOX</span></div>
    {message && <div className="intelligence-message" role="status">{message}</div>}
    {!isOperator ? <div className="panel case-card"><span className="eyebrow">{department} / RECIPIENT INBOX</span>
      <h3>Handoffs awaiting your team</h3>
      <p className="case-muted">Packets are internal to this app. A confirmed read is an investigative lead, not an automatic field instruction.</p>
      <button className="secondary" onClick={() => refresh()} disabled={busy}>Refresh inbox</button>
      {inbox.length === 0 && <p className="case-muted">No handoffs addressed to this department.</p>}
      {inbox.map(item => <div className="case-record" key={item.id}>
        <strong>{item.packet.case_reference} · {item.packet.plate}</strong>
        <span>{item.packet.kind.replaceAll('_', ' ')} · {item.packet.priority} · {item.status}</span>
        <small>Last confirmed: {item.packet.last_confirmed.camera_id} at {stamp(item.packet.last_confirmed.display_time_utc)}{item.packet.last_confirmed.time_approximate ? ' (approximate)' : ''}</small>
        <small>{item.packet.uncertainty}</small>
        <small>{item.packet.suggestion_basis}</small>
        <small>Suggested cameras: {item.packet.suggested_cameras.length ? item.packet.suggested_cameras.map(row => `${row.camera_id} (${row.health})`).join(', ') : 'none verified in this department'}</small>
        <p>{item.note}</p>
        {item.status === 'pending' && <button disabled={busy} onClick={() => action(() => api(`/cases/handoffs/${item.id}/acknowledge`,
          { method: 'POST', headers: { 'X-CSRF-Token': csrf },
            body: JSON.stringify({ note: 'Received by district desk for independent review.' }) }),
          'Handoff acknowledged and logged.')}>Acknowledge receipt</button>}
      </div>)}
    </div> : <>
      <div className="case-grid">
        <form className="panel case-card" onSubmit={create} onInvalidCapture={event => {
          setFormError(true)
          setFormMessage(`${event.target.closest('label')?.textContent?.trim() || 'A field'} needs a valid value.`)
        }}><span className="eyebrow">OPEN AN INCIDENT</span><h3>Start with the case</h3>
          <div className="case-form-grid">
            <label>Case reference<input required maxLength="80" value={form.reference} onChange={e => setForm({ ...form, reference: e.target.value })} placeholder="FIR or demo reference" /></label>
            <label>Type<select value={form.kind} onChange={e => setForm({ ...form, kind: e.target.value })}><option value="hit_and_run">Hit and run</option><option value="stolen_vehicle">Stolen vehicle</option></select></label>
            <label>Plate or known fragment<input required minLength="3" maxLength="32" value={form.plate_query} onChange={e => setForm({ ...form, plate_query: e.target.value })} placeholder="GJ01AB1234 or fragment" /></label>
            <label>Plate search<select value={form.query_mode} onChange={e => setForm({ ...form, query_mode: e.target.value })}><option value="exact">Exact plate</option><option value="partial">Partial candidate search</option></select></label>
            <label>Priority<select value={form.priority} onChange={e => setForm({ ...form, priority: e.target.value })}><option value="urgent">Urgent</option><option value="routine">Routine</option></select></label>
            <label>Incident time<input required type="datetime-local" value={form.incident_utc} onChange={e => setForm({ ...form, incident_utc: e.target.value })} /></label>
            <label>Search until (optional)<input type="datetime-local" value={form.search_until_utc} onChange={e => setForm({ ...form, search_until_utc: e.target.value })} /></label>
            <label>Lead department<input required maxLength="200" value={form.lead_department} onChange={e => setForm({ ...form, lead_department: e.target.value })} placeholder="Ahmedabad Police" /></label>
            <label>Latitude<input required type="number" step="any" value={form.incident_latitude} onChange={e => setForm({ ...form, incident_latitude: e.target.value })} /></label>
            <label>Longitude<input required type="number" step="any" value={form.incident_longitude} onChange={e => setForm({ ...form, incident_longitude: e.target.value })} /></label>
          </div>
          <label>Vehicle description<textarea value={form.vehicle_description} maxLength="500" onChange={e => setForm({ ...form, vehicle_description: e.target.value })} placeholder="Colour, make and witness description; optional" /></label>
          <button disabled={busy}>{busy ? 'Opening case…' : 'Open case'}</button>
          {formMessage && <p className={`case-form-message${formError ? ' is-error' : ''}`}
            role={formError ? 'alert' : 'status'}>{formMessage}</p>}
        </form>
        <div className="panel case-card"><span className="eyebrow">SHIFT-CHANGE BRIEFING</span><h3>Open cases to carry forward</h3>
          <p className="case-muted">Generated from current case, evidence, handoff and camera-health records.</p>
          <button className="secondary" onClick={() => refresh()} disabled={busy}>Refresh briefing</button>
          {(briefing?.open_cases || []).length === 0 && <p className="case-muted">No open cases.</p>}
          {(briefing?.open_cases || []).map(row => <button type="button" className="case-list-item" key={row.case_id} onClick={() => choose(row.case_id)}>
            <strong>{row.reference}</strong><span>{row.kind.replaceAll('_', ' ')} · {row.priority}</span>
            <small>{row.pending_handoffs} pending handoff(s) · {row.nearby_camera_gaps} unverified nearby feeds</small>
            <small>{row.last_confirmed ? `Last confirmed: ${row.last_confirmed.camera_id}` : 'No confirmed sighting yet'}</small>
          </button>)}
        </div>
      </div>
      {detail && <div className="panel case-card case-detail"><div className="case-title"><div><span className="eyebrow">CASE {detail.case.reference}</span>
        <h3>{detail.case.kind.replaceAll('_', ' ')} · {detail.case.status}</h3></div><span className="panel-tag">{detail.case.priority.toUpperCase()}</span></div>
        <p className="case-muted">Incident: {stamp(detail.case.incident_utc)} · {detail.case.lead_department} · target query {detail.case.plate_query}</p>
        <div className="case-summary"><div><strong>{detail.evidence.confirmed.length}</strong><span>Confirmed, verified reads</span></div>
          <div><strong>{detail.evidence.candidates.length}</strong><span>Review candidates</span></div>
          <div><strong>{detail.camera_plan.unavailable_or_unverified.length}</strong><span>Nearby camera gaps</span></div>
          <div><strong>{detail.handoffs.filter(item => item.status === 'pending').length}</strong><span>Pending handoffs</span></div></div>
        <p className="case-muted">{detail.camera_plan.basis} {detail.evidence.warning}</p>
        <div className="case-sections">
          <div><h4>Hit-and-run / stolen-vehicle triage</h4>
            {detail.evidence.confirmed.length === 0 && <p className="case-muted">No confirmed, hash-verified read matches this query. Review candidate OCR; no district handoff can be sent yet.</p>}
            {detail.evidence.confirmed.map(row => <div className="case-record" key={row.id}>
              <strong>{row.effective_plate} · {row.camera_id}</strong>
              <small>{stamp(row.display_time_utc)}{row.display_time_is_approximate ? ' · approximate clock' : ''} · {row.department}</small>
              <small>Evidence hash verified · {row.effective_status}</small>
              <div className="case-actions"><button disabled={busy || detail.case.status !== 'open'} onClick={() => handoff(row.id)}>Queue district handoff</button>
                {!detail.case.pursuit_id && <button className="secondary" disabled={busy || detail.case.status !== 'open'} onClick={() => pursue(row.id)}>Link pursuit</button>}</div>
            </div>)}
            {detail.evidence.candidates.slice(0, 10).map(row => <div className="case-record" key={row.id}>
              <strong>{row.effective_plate} · candidate</strong><small>{row.camera_id} · {row.effective_status} · {stamp(row.display_time_utc)}</small>
              <small>Review in Evidence Journey before operational use.</small></div>)}
            <label>Recipient department<select value={recipient} onChange={e => setRecipient(e.target.value)}><option value="">Choose destination</option>
              {departments.filter(value => value !== detail.case.lead_department).map(value => <option key={value}>{value}</option>)}</select></label>
            <label>Handoff note<textarea value={handoffNote} onChange={e => setHandoffNote(e.target.value)} /></label>
            {detail.case.pursuit_id && <p className="case-muted">Pursuit linked: {detail.case.pursuit_id}. Use the existing Journey panel to run measured scheduling.</p>}
            {detail.case.pursuit_id && <button className="secondary" disabled={busy || detail.case.status !== 'open'} onClick={startMeasuredPursuit}>Start measured pursuit</button>}
            {detail.case.kind === 'stolen_vehicle' && detail.case.query_mode === 'exact' && detail.representative_watchlist.length === 0 &&
              <button className="secondary" disabled={busy} onClick={addRepresentativeWatchlist}>Add representative case watchlist</button>}
            {detail.representative_watchlist.length > 0 && <p className="case-muted">Representative watchlist entry linked by exact plate; {detail.alerts.length} matching alert(s). Official eGujCop/VAHAN integration is not configured.</p>}
          </div>
          <div><h4>Camera-specific blind spots</h4>
            {detail.camera_plan.unavailable_or_unverified.length === 0 && <p className="case-muted">No unverified nearby camera in this registry snapshot.</p>}
            {detail.camera_plan.unavailable_or_unverified.map(row => <div className="case-record" key={row.camera_id}>
              <strong>{row.name} · {row.health}</strong><small>{row.department} · {row.distance_km} km from incident</small></div>)}
            <h4>Working cameras to inspect</h4>
            {detail.camera_plan.working_alternatives.map(row => <div className="case-record" key={row.camera_id}>
              <strong>{row.name}</strong><small>{row.department} · {row.distance_km} km · decoded online</small></div>)}
            <p className="case-muted">These are geographic alternatives only. Check actual road visibility and permissions before using them.</p>
          </div>
        </div>
        <h4>Action and handoff history</h4>
        {detail.handoffs.map(item => <div className="case-record" key={item.id}><strong>{item.recipient_department} · {item.status}</strong>
          <small>{stamp(item.created_utc)} · sighting {item.sighting_id}</small><small>{item.acknowledgement_note || item.note}</small></div>)}
        {detail.events.slice().reverse().map(item => <div className="case-event" key={item.id}>
          <strong>{item.kind.replaceAll('_', ' ')}</strong><span>{item.detail}</span><small>{stamp(item.at_utc)} · {item.actor}</small></div>)}
        <div className="case-actions"><input aria-label="Case note" value={note} onChange={e => setNote(e.target.value)} placeholder="Add a shift or investigation note" />
          <button disabled={busy || note.trim().length < 5} onClick={() => action(async () => {
            await api(`/cases/${selectedId}/notes`, { method: 'POST', headers: { 'X-CSRF-Token': csrf }, body: JSON.stringify({ note }) }); setNote('')
          }, 'Case note recorded.')}>Record note</button>
          <button className="secondary" disabled={busy} onClick={sign}>Sign case timeline</button>
          {snapshot && <button className="secondary" onClick={downloadSnapshot}>Download signed JSON</button>}
          {detail.case.status === 'open' && <button className="secondary" disabled={busy} onClick={() => action(() => api(`/cases/${selectedId}/status`,
            { method: 'PUT', headers: { 'X-CSRF-Token': csrf }, body: JSON.stringify({ status: 'closed', note: 'Closed by operator after review.' }) }),
          'Case closed.')}>Close case</button>}</div>
      </div>}
    </>}
  </section>
}
