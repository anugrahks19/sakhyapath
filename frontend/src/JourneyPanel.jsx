import React, { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import PursuitPanel from './PursuitPanel.jsx'


function JourneyMap({ journey }) {
  const container = useRef(null)
  const map = useRef(null)
  const layer = useRef(null)

  useEffect(() => {
    map.current = L.map(container.current, { zoomControl: false }).setView([22.6, 72.6], 7)
    L.control.zoom({ position: 'bottomright' }).addTo(map.current)
    const tiles = import.meta.env.VITE_MAP_TILE_URL || 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
    L.tileLayer(tiles, { maxZoom: 18, attribution: '© OpenStreetMap contributors' }).addTo(map.current)
    layer.current = L.layerGroup().addTo(map.current)
    return () => { map.current?.remove(); map.current = null }
  }, [])

  useEffect(() => {
    if (!layer.current || !map.current) return
    layer.current.clearLayers()
    const records = journey?.records || []
    const byId = new Map(records.map(item => [item.id, item]))
    for (const link of journey?.links || []) {
      const first = byId.get(link.from_sighting_id)
      const second = byId.get(link.to_sighting_id)
      if (!first || !second) continue
      L.polyline([[first.latitude, first.longitude], [second.latitude, second.longitude]], {
        color: link.status === 'implausible' ? '#d36e55' : '#527ad3',
        weight: 2, opacity: .85, dashArray: '6 7',
      }).addTo(layer.current)
    }
    for (const item of records) {
      const observed = journey.observations.some(point => point.id === item.id)
      const color = observed ? '#356bd8' : item.effective_status === 'rejected' ? '#a3afbe' : '#db9b39'
      const marker = L.circleMarker([item.latitude, item.longitude], {
        radius: observed ? 8 : 7, color, weight: 2,
        fillColor: observed ? color : '#fff', fillOpacity: observed ? 1 : .85,
      }).addTo(layer.current)
      const label = document.createElement('span')
      label.textContent = `${item.camera_id} · ${item.effective_status} · ${item.effective_plate}`
      marker.bindTooltip(label)
    }
    if (records.length) {
      map.current.fitBounds(L.latLngBounds(records.map(item => [item.latitude, item.longitude])).pad(.25),
        { maxZoom: 12 })
    }
    setTimeout(() => map.current?.invalidateSize(), 0)
  }, [journey])

  return <div className="journey-map" ref={container} aria-label="Evidence journey map" />
}


export default function JourneyPanel({ api, csrf, cameras, role }) {
  const [plate, setPlate] = useState('')
  const [fromTime, setFromTime] = useState('')
  const [toTime, setToTime] = useState('')
  const [cameraId, setCameraId] = useState('')
  const [reviewStatus, setReviewStatus] = useState('')
  const [saved, setSaved] = useState([])
  const [journey, setJourney] = useState(null)
  const [editingId, setEditingId] = useState(null)
  const [correctedPlate, setCorrectedPlate] = useState('')
  const [reviewNote, setReviewNote] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => { api('/pursuits').then(setSaved).catch(cause => setMessage(cause.message)) }, [api])

  async function openJourney(id) {
    try {
      setBusy(true)
      setJourney(await api(`/pursuits/${encodeURIComponent(id)}/journey`))
      setMessage('')
    } catch (cause) { setMessage(cause.message) }
    finally { setBusy(false) }
  }

  async function search(event) {
    event.preventDefault()
    try {
      setBusy(true)
      const pursuit = await api('/pursuits', {
        method: 'POST', headers: { 'X-CSRF-Token': csrf },
        body: JSON.stringify({
          plate, from_utc: fromTime ? new Date(fromTime).toISOString() : null,
          to_utc: toTime ? new Date(toTime).toISOString() : null,
          camera_id: cameraId || null, review_status: reviewStatus || null,
        }),
      })
      setSaved(previous => [pursuit, ...previous].slice(0, 30))
      setJourney(await api(`/pursuits/${pursuit.id}/journey`))
      setMessage('')
    } catch (cause) { setMessage(cause.message) }
    finally { setBusy(false) }
  }

  async function review(item, decision) {
    if (reviewNote.trim().length < 5) { setMessage('Add a short review reason before saving.'); return }
    try {
      setBusy(true)
      await api(`/sightings/${item.id}/review`, {
        method: 'POST', headers: { 'X-CSRF-Token': csrf },
        body: JSON.stringify({ decision,
          corrected_plate: decision === 'confirmed' ? correctedPlate || null : null,
          note: reviewNote }),
      })
      setEditingId(null); setCorrectedPlate(''); setReviewNote('')
      setJourney(await api(`/pursuits/${journey.pursuit.id}/journey`))
      setMessage('Review saved. The original OCR and evidence remain intact.')
    } catch (cause) { setMessage(cause.message) }
    finally { setBusy(false) }
  }

  return <section className="journey-section">
    <div className="intelligence-heading"><div><span className="eyebrow">MODULE 03 / EVIDENCE JOURNEY</span>
      <h2>Follow the evidence<span>.</span></h2>
      <p>Find past sightings by registration. The map separates observations from possible connections.</p></div>
      <span className="panel-tag">HISTORICAL SEARCH</span></div>
    {message && <div className="intelligence-message" role="status">{message}</div>}
    <div className="panel journey-search-card">
      <form onSubmit={search} className="journey-form">
        <label className="journey-plate">Registration number<input aria-label="Search registration" value={plate}
          onChange={event => setPlate(event.target.value)} placeholder="GJ01AB1234" required /></label>
        <label>From (optional)<input aria-label="From time" type="datetime-local" value={fromTime}
          onChange={event => setFromTime(event.target.value)} /></label>
        <label>To (optional)<input aria-label="To time" type="datetime-local" value={toTime}
          onChange={event => setToTime(event.target.value)} /></label>
        <label>Camera<select aria-label="Journey camera" value={cameraId} onChange={event => setCameraId(event.target.value)}>
          <option value="">All permitted cameras</option>
          {cameras.map(camera => <option key={camera.camera_id} value={camera.camera_id}>{camera.display_name}</option>)}
        </select></label>
        <label>Review state<select aria-label="Journey review state" value={reviewStatus}
          onChange={event => setReviewStatus(event.target.value)}>
          <option value="">All states</option><option value="confirmed">Model confirmed</option>
          <option value="candidate">Candidate</option><option value="reviewed_confirmed">Reviewer confirmed</option>
          <option value="rejected">Rejected</option>
        </select></label>
        <button disabled={busy} type="submit">{busy ? 'Searching…' : 'Build journey'}</button>
      </form>
      {saved.length > 0 && <div className="recent-journeys"><small>RECENT SEARCHES</small>
        {saved.slice(0, 5).map(item => <button key={item.id} type="button" onClick={() => openJourney(item.id)}>
          {item.target_plate}</button>)}</div>}
    </div>
    {journey && <>
      <div className="journey-result-top"><div><span className="eyebrow">SEARCH RESULT</span>
        <h3>{journey.pursuit.target_plate}</h3><p>{journey.counts.observations} supported observations · {journey.counts.candidates} candidates · {journey.counts.rejected} rejected</p></div>
        <a className="journey-download" href={`/api/v1/pursuits/${encodeURIComponent(journey.pursuit.id)}/report`}>
          Download PDF report ↗</a></div>
      <div className="journey-layout">
        <div className="panel journey-map-card"><div className="panel-head"><div><span className="eyebrow">GEOSPATIAL RECORD</span><h3>Observed camera points</h3></div></div>
          <JourneyMap journey={journey} />
          <p className="journey-map-note"><span className="journey-dot solid" /> Evidence supported
            <span className="journey-dot hollow" /> Candidate / unsupported
            <span className="journey-dash" /> Possible link</p></div>
        <div className="panel journey-contract"><span className="eyebrow">TIME CONTRACT</span>
          <h3>Clock certainty matters.</h3>
          <p>Source PTS describes time within one stream. When a shared clock is unverified, order uses receive time as an approximation. Dashed lines are inferred connections, never road routes.</p>
          {journey.gaps.length > 0 && <div className="journey-gaps">{journey.gaps.map(gap => <p key={gap}>◇ {gap}</p>)}</div>}
          {journey.links.map((link, index) => <p key={`${link.from_sighting_id}-${link.to_sighting_id}`} className={`journey-link ${link.status}`}>
            {index + 1}. {link.from_camera_id} → {link.to_camera_id} · {link.distance_km_straight_line} km straight-line · {link.status.replaceAll('_', ' ')}
          </p>)}</div>
      </div>
      <div className="panel journey-records"><div className="panel-head"><div><span className="eyebrow">AUDITABLE HISTORY</span><h3>All matching records</h3></div>
        <span className="panel-tag">{journey.counts.records} RECORDS</span></div>
        {journey.records.length === 0 && <p className="journey-empty">No earlier sightings match this registration and filter.</p>}
        {journey.records.map((item, index) => <article className="journey-record" key={item.id}>
          <div className="journey-record-num">{String(index + 1).padStart(2, '0')}</div>
          <div className="journey-record-body"><div className="journey-record-heading"><strong>{item.display_name}</strong>
            <span className={`journey-status ${item.effective_status}`}>{item.effective_status.replaceAll('_', ' ')}</span></div>
            <p>{item.camera_id} · {item.department} · {item.source_system === 'sentinel' ? 'Government' : 'Owned'} / {item.source_mode.replaceAll('_', ' ')}</p>
            <p><strong>{item.effective_plate}</strong> · Raw OCR {item.raw_text} · {item.display_time_is_approximate ? 'Approx. receive UTC' : 'Operator-attested mapped UTC'} {item.display_time_utc}</p>
            <p>PTS {item.source_pts == null ? 'unavailable' : item.source_pts.toFixed(3)} · Generation {item.stream_generation} · Evidence {item.evidence_status.replaceAll('_', ' ')}</p>
            <p className="journey-hash">SHA-256 {item.evidence_sha256}</p>
            {item.review_history?.length > 0 && <p>Review: {item.review_history.at(-1).decision} by {item.review_history.at(-1).actor}{item.review_history.at(-1).corrected_plate ? ` · corrected ${item.review_history.at(-1).corrected_plate}` : ''}</p>}
            {editingId === item.id ? <div className="journey-review-form">
              <input aria-label="Corrected registration" placeholder="Corrected plate (optional)" value={correctedPlate}
                onChange={event => setCorrectedPlate(event.target.value)} />
              <input aria-label="Review note" placeholder="Why? Add an audit note" value={reviewNote}
                onChange={event => setReviewNote(event.target.value)} />
              <button disabled={busy} onClick={() => review(item, 'confirmed')}>Confirm</button>
              <button disabled={busy} className="secondary" onClick={() => review(item, 'rejected')}>Reject</button>
              <button className="quiet" onClick={() => setEditingId(null)}>Cancel</button></div>
              : <button className="quiet journey-review-button" onClick={() => { setEditingId(item.id); setCorrectedPlate(item.corrected_plate || ''); setReviewNote('') }}>Review record</button>}
          </div>
          {item.evidence_supported ? <img src={item.evidence_url} alt={`Evidence crop from ${item.camera_id}`} loading="lazy" />
            : <div className="journey-evidence-unavailable">Evidence<br />unverified</div>}
        </article>)}</div>
      <PursuitPanel api={api} csrf={csrf} journey={journey} role={role}
        onRefresh={() => openJourney(journey.pursuit.id)} />
    </>}
  </section>
}
