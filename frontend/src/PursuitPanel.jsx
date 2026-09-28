import React, { useEffect, useState } from 'react'

const names = {
  observed: 'Observed',
  'not observed in sampled frames': 'Not observed in sampled frames',
  'feed unavailable': 'Feed unavailable',
  'insufficient coverage': 'Insufficient coverage',
}

export default function PursuitPanel({ api, csrf, journey, role, onRefresh }) {
  const id = journey.pursuit.id
  const [rankings, setRankings] = useState(null)
  const [live, setLive] = useState({ schedule: journey.active_pursuit, coverage: journey.coverage })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setLive({ schedule: journey.active_pursuit, coverage: journey.coverage })
    api(`/pursuits/${encodeURIComponent(id)}/rankings`).then(setRankings).catch(cause => setError(cause.message))
  }, [api, id, journey])

  useEffect(() => {
    if (!live.schedule?.active) return undefined
    const timer = setInterval(async () => {
      try {
        const [schedule, coverage, nextRankings] = await Promise.all([
          api(`/pursuits/${encodeURIComponent(id)}/schedule`),
          api(`/pursuits/${encodeURIComponent(id)}/coverage`),
          api(`/pursuits/${encodeURIComponent(id)}/rankings`),
        ])
        setLive({ schedule, coverage }); setRankings(nextRankings)
      } catch (cause) { setError(cause.message) }
    }, 5000)
    return () => clearInterval(timer)
  }, [api, id, live.schedule?.active])

  async function toggle() {
    setBusy(true); setError('')
    try {
      await api(`/pursuits/${encodeURIComponent(id)}/schedule`, {
        method: live.schedule?.active ? 'DELETE' : 'POST',
        headers: { 'X-CSRF-Token': csrf },
      })
      await onRefresh()
    } catch (cause) { setError(cause.message) }
    finally { setBusy(false) }
  }

  const schedule = live.schedule || {}
  const windows = live.coverage?.windows || []
  const measurement = schedule.measurement

  return <section className="pursuit-section">
    <div className="intelligence-heading"><div><span className="eyebrow">MODULE 04 / ACTIVE PURSUIT</span>
      <h2>Look where the evidence leads<span>.</span></h2>
      <p>Transparent camera ranking, measured frame budget, and a coverage record that shows uncertainty.</p></div>
      <span className="panel-tag">{schedule.active ? 'SCHEDULER ACTIVE' : 'SCHEDULER STANDBY'}</span></div>
    {error && <div className="intelligence-message" role="alert">{error}</div>}
    <div className="pursuit-grid">
      <div className="panel pursuit-summary">
        <span className="eyebrow">CAPACITY CONTRACT</span>
        <h3>{measurement ? `${measurement.budget_fps.toFixed(2)} fps` : 'Benchmark needed'}</h3>
        <p>{measurement ? `70% of ${measurement.sustainable_fps.toFixed(2)} measured analyzed fps · 30% reserve · ${measurement.feed_count} ${measurement.source_mode.replaceAll('_', ' ')} feed(s)` : 'Run an end-to-end owned-feed benchmark and record its counts before starting a pursuit.'}</p>
        {measurement && <p className="pursuit-fine">{measurement.codec} · {measurement.resolution} · {measurement.model_provider} · {measurement.duration_seconds}s measured</p>}
        {role === 'operator' && <button onClick={toggle} disabled={busy || (!measurement && !schedule.active)}>
          {busy ? 'Applying…' : schedule.active ? 'Stop pursuit sampling' : 'Start measured pursuit'}</button>}
        {schedule.schedule && <div className="pursuit-revision">Revision {schedule.schedule.revision} · {schedule.schedule.reason} · {schedule.requested_total_fps} fps requested · {schedule.current_applied_total_fps} fps currently acknowledged</div>}
      </div>
      <div className="panel pursuit-summary pursuit-contract">
        <span className="eyebrow">LATEST CONFIRMED EVIDENCE</span>
        <h3>{rankings?.latest_confirmed_camera_id || 'No confirmed sighting'}</h3>
        <p>{rankings?.basis || 'Loading ranking basis…'}</p>
        <p>Heuristic scores are not probabilities. Direction and road travel time are unknown. A candidate OCR reading never moves the scheduler by itself.</p>
      </div>
    </div>
    <div className="panel pursuit-table-card"><div className="panel-head"><div><span className="eyebrow">CAMERA PRIORITIES</span><h3>Next places to sample</h3></div></div>
      <div className="pursuit-list">
        {(rankings?.rankings || []).map(row => {
          const allocation = schedule.allocations?.find(item => item.camera_id === row.camera_id)
          return <div className="pursuit-row" key={row.camera_id}>
            <span className="pursuit-rank">{String(row.rank).padStart(2, '0')}</span>
            <div><strong>{row.display_name}</strong><small>{row.camera_id} · {row.health_status} · {row.factors.distance_km_straight_line == null ? 'No origin' : `${row.factors.distance_km_straight_line} km straight-line`}</small></div>
            <div className="pursuit-factors"><span>Heuristic {row.score.toFixed(3)}</span><small>health {row.factors.health} · resolution proxy {row.factors.readability_resolution_proxy} · queue age {row.factors.queue_age_ms == null ? 'unmeasured' : `${row.factors.queue_age_ms} ms`}</small></div>
            <div className="pursuit-rate"><strong>{allocation ? `${allocation.requested_fps.toFixed(2)} fps` : 'Standby'}</strong><small>{allocation ? `${allocation.current_applied_fps.toFixed(2)} fps applied now` : 'No allocation yet'}</small></div>
          </div>
        })}
        {!rankings?.rankings?.length && <p className="journey-empty">No permitted camera has a supported source URL.</p>}
      </div>
    </div>
    <div className="panel pursuit-table-card"><div className="panel-head"><div><span className="eyebrow">COVERAGE INTEGRITY LEDGER</span><h3>What the sampled video supports</h3></div><span className="panel-tag">{windows.length} WINDOWS</span></div>
      <div className="pursuit-ledger-note">“Not observed” refers only to analyzed frames. It never proves absence from the road or from unsampled video.</div>
      <div className="pursuit-list">
        {windows.map(window => <div className="pursuit-row coverage-row" key={`${window.schedule_id}-${window.camera_id}`}>
          <span className={`coverage-mark ${window.result_code.replaceAll(' ', '-')}`} />
          <div><strong>{window.camera_id}</strong><small>Revision {window.revision} · {window.health} · {window.window_start_utc}</small></div>
          <div className="pursuit-factors"><span className="coverage-result">{names[window.result_code]}</span><small>{window.reason}</small></div>
          <div className="pursuit-rate"><strong>{window.analyzed_frames}/{window.planned_frames}</strong><small>analyzed/planned · {window.received_frames} received · {window.decode_errors} errors</small></div>
        </div>)}
        {!windows.length && <p className="journey-empty">Start a measured pursuit to create auditable camera windows.</p>}
      </div>
    </div>
  </section>
}
