import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import './style.css'
import JourneyPanel from './JourneyPanel.jsx'
import CaseBridgePanel from './CaseBridgePanel.jsx'

async function api(path, options = {}) {
  const response = await fetch(`/api/v1${path}`, {
    credentials: 'include',
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  })
  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail)) {
        detail = body.detail.map(item => `${item.loc?.slice(1).join('.') || 'Input'}: ${item.msg}`).join('; ')
      }
    } catch { /* non-JSON error */ }
    throw new Error(detail)
  }
  return response.json()
}

function CameraMap({ cameras, selectedId, onSelect }) {
  const container = useRef(null)
  const map = useRef(null)
  const layer = useRef(null)
  const fittedIds = useRef('')

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
    const points = []
    for (const camera of cameras) {
      const point = [camera.latitude, camera.longitude]
      points.push(point)
      const color = camera.health_status === 'online' ? '#0fb58d'
        : camera.health_status === 'degraded' ? '#e7a742' : '#a5b1c0'
      const marker = L.circleMarker(point, {
        radius: camera.camera_id === selectedId ? 11 : 8,
        color: '#ffffff', weight: 3, fillColor: color, fillOpacity: 1,
      })
      marker.bindTooltip(camera.display_name)
      marker.on('click', () => onSelect(camera.camera_id))
      marker.addTo(layer.current)
    }
    const ids = cameras.map(camera => camera.camera_id).sort().join('|')
    if (points.length > 0 && ids !== fittedIds.current) {
      map.current.fitBounds(L.latLngBounds(points).pad(0.3), { maxZoom: 12 })
      fittedIds.current = ids
    }
  }, [cameras, selectedId, onSelect])

  return <div className="map" ref={container} aria-label="GIS camera map" />
}

function Login({ onLogin, startupError }) {
  const [key, setKey] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  async function submit(event) {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      const result = await api('/auth/login', { method: 'POST', body: JSON.stringify({ operator_key: key }),
        signal: AbortSignal.timeout(10000) })
      setKey('')
      onLogin(result)
    } catch (cause) {
      setError(cause.name === 'TimeoutError' ? 'The server did not respond. Please try again shortly.' : cause.message)
    } finally { setSubmitting(false) }
  }
  return <main className="login-screen">
    <div className="login-ambient login-ambient-one" aria-hidden="true" /><div className="login-ambient login-ambient-two" aria-hidden="true" />
    <div className="login-card">
      <div className="login-brand"><div className="brand-icon">S</div><div><strong>SakhyaPath</strong><small>GUJARAT CAMERA INTELLIGENCE</small></div></div>
      <div className="login-separator" />
      <span className="eyebrow">SECURE OPERATIONS PORTAL</span>
      <h1>Welcome back<span>.</span></h1>
      <p>Sign in to inspect camera locations, verified feed health, and authorised live previews.</p>
      <form onSubmit={submit}>
        <label htmlFor="key">Operator key</label>
        <input id="key" type="password" value={key} onChange={e => setKey(e.target.value)}
          autoComplete="off" placeholder="Enter your operator key" required />
        <small style={{display: 'block', marginTop: '0.5rem', color: '#666'}}>For judges: use key <strong>demo</strong></small>
        <button type="submit" disabled={submitting}>{submitting ? 'Connecting…' : 'Open camera grid'} <span aria-hidden="true">↗</span></button>
      </form>
      {(error || startupError) && <p className="error" role="alert">{error || startupError}</p>}
      <small><span className="secure-dot" /> Authorised sources only · Session protected</small>
    </div>
    <p className="login-caption">SAKHYAPATH / CAMERA INTELLIGENCE · MODULES 01–04</p>
  </main>
}

function ImportCamera({ csrf, onDone, onClose }) {
  const [form, setForm] = useState({ camera_id: '', display_name: '', department: 'Owned test',
    latitude: '23.0225', longitude: '72.5714', source_mode: 'owned_replay', rtsp_url: '', hls_url: '' })
  const [error, setError] = useState('')
  function change(event) { setForm({ ...form, [event.target.name]: event.target.value }) }
  async function submit(event) {
    event.preventDefault()
    try {
      await api('/cameras/import', {
        method: 'POST', headers: { 'X-CSRF-Token': csrf },
        body: JSON.stringify([{ ...form, latitude: Number(form.latitude), longitude: Number(form.longitude),
          rtsp_url: form.rtsp_url || null, hls_url: form.hls_url || null }]),
      })
      onDone()
    } catch (cause) { setError(cause.message) }
  }
  return <div className="modal-backdrop"><form className="modal" onSubmit={submit}>
    <div className="modal-top"><div><span className="eyebrow">CONTROLLED SOURCE</span><h2>Add owned camera</h2></div>
      <button className="quiet" type="button" onClick={onClose}>Close</button></div>
    <label>ID<input name="camera_id" value={form.camera_id} onChange={change} required /></label>
    <label>Name<input name="display_name" value={form.display_name} onChange={change} required /></label>
    <label>Department<input name="department" value={form.department} onChange={change} required /></label>
    <div className="form-row">
      <label>Latitude<input name="latitude" type="number" step="any" value={form.latitude} onChange={change} required /></label>
      <label>Longitude<input name="longitude" type="number" step="any" value={form.longitude} onChange={change} required /></label>
    </div>
    <label>Source label<select name="source_mode" value={form.source_mode} onChange={change}>
      <option value="owned_replay">Owned replay</option><option value="owned_live">Owned live</option>
    </select></label>
    <label>RTSP URL<input name="rtsp_url" value={form.rtsp_url} onChange={change} placeholder="rtsp://…" /></label>
    <label>HLS fallback URL<input name="hls_url" value={form.hls_url} onChange={change} placeholder="http://…/index.m3u8" /></label>
    <p className="help">URLs are stored server-side and never returned to the dashboard.</p>
    {error && <p className="error" role="alert">{error}</p>}
    <button type="submit">Save camera</button>
  </form></div>
}

function CameraPreview({ camera }) {
  const [imageUrl, setImageUrl] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    let timer = null
    let image = null
    let controller = null
    async function nextFrame() {
      if (document.visibilityState !== 'visible') return
      controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 6000)
      try {
        const response = await fetch(`/api/v1/cameras/${encodeURIComponent(camera.camera_id)}/snapshot.jpg`, {
          credentials: 'include', cache: 'no-store', signal: controller.signal,
        })
        if (!response.ok) throw new Error(`Frame unavailable (${response.status})`)
        const blob = await response.blob()
        if (!active) return
        const url = URL.createObjectURL(blob)
        if (image) URL.revokeObjectURL(image)
        image = url
        setImageUrl(url)
        setError('')
      } catch (cause) {
        if (active && cause.name !== 'AbortError') {
          if (image) URL.revokeObjectURL(image)
          image = null
          setImageUrl(null)
          setError(cause.message)
        }
      } finally {
        clearTimeout(timeout)
        if (active && document.visibilityState === 'visible') timer = setTimeout(nextFrame, 1000)
      }
    }
    function visibilityChanged() {
      if (document.visibilityState === 'hidden') {
        clearTimeout(timer)
        controller?.abort()
      } else if (active) {
        clearTimeout(timer)
        nextFrame()
      }
    }
    document.addEventListener('visibilitychange', visibilityChanged)
    nextFrame()
    return () => {
      active = false
      document.removeEventListener('visibilitychange', visibilityChanged)
      clearTimeout(timer)
      controller?.abort()
      if (image) URL.revokeObjectURL(image)
    }
  }, [camera.camera_id])

  return imageUrl ? <img src={imageUrl} alt={`Live preview of ${camera.display_name}`} />
    : <div className="preview-empty"><span>◉</span><p>{error || 'Connecting to feed…'}</p></div>
}

function IntelligencePanel({ csrf, selectedId, role }) {
  const [analysis, setAnalysis] = useState(null)
  const [sightings, setSightings] = useState([])
  const [alerts, setAlerts] = useState([])
  const [watchlist, setWatchlist] = useState([])
  const [plate, setPlate] = useState('')
  const [expiresAt, setExpiresAt] = useState('')
  const [sampleFps, setSampleFps] = useState('2')
  const [message, setMessage] = useState('')

  const refreshRecords = useCallback(async () => {
    try {
      const [found, hits, entries] = await Promise.all([
        api('/sightings?limit=12'), api('/alerts'),
        role === 'operator' ? api('/watchlist') : Promise.resolve([]),
      ])
      setSightings(found); setAlerts(hits); setWatchlist(entries)
    } catch (cause) { setMessage(cause.message) }
  }, [role])

  useEffect(() => {
    refreshRecords()
    const timer = setInterval(refreshRecords, 10000)
    const stream = new EventSource('/api/v1/alerts/stream')
    let eventRefresh = null
    const scheduleRefresh = () => {
      if (eventRefresh || document.visibilityState !== 'visible') return
      eventRefresh = setTimeout(() => { eventRefresh = null; refreshRecords() }, 1000)
    }
    stream.addEventListener('SightingCreated', scheduleRefresh)
    stream.addEventListener('AlertCreated', scheduleRefresh)
    stream.addEventListener('AlertAcknowledged', scheduleRefresh)
    document.addEventListener('visibilitychange', scheduleRefresh)
    return () => { clearInterval(timer); clearTimeout(eventRefresh); stream.close()
      document.removeEventListener('visibilitychange', scheduleRefresh) }
  }, [refreshRecords])

  useEffect(() => {
    if (!selectedId) { setAnalysis(null); return }
    let active = true
    const read = () => api(`/cameras/${encodeURIComponent(selectedId)}/analysis`)
      .then(value => { if (active) setAnalysis(value) })
      .catch(cause => { if (active) setMessage(cause.message) })
    read()
    const timer = setInterval(read, 2000)
    return () => { active = false; clearInterval(timer) }
  }, [selectedId])

  async function toggleAnalysis() {
    if (!selectedId) return
    try {
      const result = await api(`/cameras/${encodeURIComponent(selectedId)}/analysis`, {
        method: analysis?.running ? 'DELETE' : 'POST',
        headers: { 'X-CSRF-Token': csrf },
        ...(analysis?.running ? {} : { body: JSON.stringify({ sample_fps: Number(sampleFps) }) }),
      })
      setAnalysis(result)
      setMessage(analysis?.running ? 'Analysis stopped.' : 'Analysis started. The first model load may take a moment.')
    } catch (cause) { setMessage(cause.message) }
  }
  async function addPlate(event) {
    event.preventDefault()
    try {
      await api('/watchlist', {
        method: 'POST', headers: { 'X-CSRF-Token': csrf },
        body: JSON.stringify({ plate, category: 'representative', source_label: 'Hackathon demo',
          expires_utc: expiresAt ? new Date(expiresAt).toISOString() : null }),
      })
      setPlate('')
      setExpiresAt('')
      setMessage('Representative watchlist entry added.')
      await refreshRecords()
    } catch (cause) { setMessage(cause.message) }
  }
  async function disablePlate(id) {
    try {
      await api(`/watchlist/${id}/disable`, {
        method: 'POST', headers: { 'X-CSRF-Token': csrf },
      })
      await refreshRecords()
    } catch (cause) { setMessage(cause.message) }
  }
  async function acknowledge(id) {
    try {
      await api(`/alerts/${id}/acknowledge`, {
        method: 'POST', headers: { 'X-CSRF-Token': csrf },
      })
      await refreshRecords()
    } catch (cause) { setMessage(cause.message) }
  }

  return <section className="intelligence">
    <div className="intelligence-heading"><div><span className="eyebrow">MODULE 02 / PLATE INTELLIGENCE</span>
      <h2>Evidence before alerts<span>.</span></h2><p>Analysis runs only on selected, authorised feeds. Readings and alerts are persisted.</p></div>
      <span className="panel-tag">{role === 'operator' ? 'REPRESENTATIVE WATCHLIST' : 'DEPARTMENT VIEW'}</span></div>
    {message && <div className="intelligence-message" role="status">{message}</div>}
    <div className="intelligence-grid">
      <div className="panel intel-card analysis-card"><div className="panel-head"><div><span className="eyebrow">FRAME ANALYSIS</span><h3>Sampling controls</h3></div><span className="inspector-glyph">◎</span></div>
        <p className="intel-lead">{selectedId ? `Selected: ${selectedId}` : 'Select a camera from the directory or map.'}</p>
        <div className="analysis-control"><label>Sample rate
          <select value={sampleFps} onChange={event => setSampleFps(event.target.value)}>
            <option value="1">1 frame / sec</option><option value="2">2 frames / sec</option>
            <option value="4">4 frames / sec</option>
          </select></label>
          <button disabled={!selectedId} onClick={toggleAnalysis}>{analysis?.running ? 'Stop analysis' : 'Start analysis'}</button></div>
        <div className="analysis-readout"><span><small>RUNNING</small><strong>{analysis?.running ? 'Yes' : 'No'}</strong></span>
          <span><small>ANALYZED</small><strong>{analysis?.analyzed ?? 0}</strong></span>
          <span><small>DROPPED</small><strong>{analysis?.dropped ?? 0}</strong></span>
          <span><small>LATENCY</small><strong>{analysis?.last_latency_ms == null ? '—' : `${Math.round(analysis.last_latency_ms)} ms`}</strong></span></div>
        <p className="provider-line">Provider: <strong>{analysis?.execution_provider || 'Uninitialized'}</strong>
          {analysis?.last_error && <span> · Error: {analysis.last_error}</span>}</p>
      </div>
      {role === 'operator' && <div className="panel intel-card watch-card"><div className="panel-head"><div><span className="eyebrow">WATCHLIST</span><h3>Demo registrations</h3></div><span className="inspector-glyph">◇</span></div>
        <form className="watch-form" onSubmit={addPlate}><input aria-label="Registration number" placeholder="e.g. GJ01AB1234"
          value={plate} onChange={event => setPlate(event.target.value)} required />
          <label className="watch-expiry">Expiry (optional)<input type="datetime-local" value={expiresAt}
            onChange={event => setExpiresAt(event.target.value)} /></label><button>Add</button></form>
        <p className="intel-help">Representative entries only. Exact confirmed sightings can trigger an alert.</p>
        <div className="intel-list">{watchlist.length === 0 && <p className="intel-empty">No entries yet.</p>}
          {watchlist.slice(0, 6).map(entry => <div className="intel-row" key={entry.id}><div><strong>{entry.plate_normalized}</strong>
            <small>{entry.active ? 'Active' : 'Disabled'} · {entry.source_label}
              {entry.expires_utc ? ` · Expires ${new Date(entry.expires_utc).toLocaleString()}` : ''}</small></div>
            {Boolean(entry.active) && <button className="quiet" onClick={() => disablePlate(entry.id)}>Disable</button>}</div>)}</div>
      </div>}
      <div className="panel intel-card"><div className="panel-head"><div><span className="eyebrow">EVIDENCE INDEX</span><h3>Latest sightings</h3></div><span className="inspector-glyph">▤</span></div>
        <div className="intel-list">{sightings.length === 0 && <p className="intel-empty">No plate sightings recorded yet.</p>}
          {sightings.map(item => <div className="intel-row sighting-row" key={item.id}>
            <img src={item.evidence_url} alt={`Evidence crop for ${item.plate_normalized}`} loading="lazy" />
            <div><strong>{item.plate_normalized}</strong><small>{item.camera_id} · {item.review_status} · PTS {item.source_pts == null ? 'unavailable' : `${item.source_pts.toFixed(2)}s`}</small></div></div>)}</div>
      </div>
      <div className="panel intel-card"><div className="panel-head"><div><span className="eyebrow">LIVE ALERTS</span><h3>Watchlist hits</h3></div><span className="inspector-glyph">◉</span></div>
        <div className="intel-list">{alerts.length === 0 && <p className="intel-empty">No confirmed watchlist hits.</p>}
          {alerts.slice(0, 12).map(item => <div className="intel-row" key={item.id}><div><strong>{item.plate_normalized}</strong>
            <small>{item.camera_id} · {item.status} · {new Date(item.created_utc).toLocaleString()}</small></div>
            {item.status === 'new' && <button className="quiet" onClick={() => acknowledge(item.id)}>Acknowledge</button>}</div>)}</div>
      </div>
    </div>
  </section>
}

function Dashboard({ csrf, role, department, onLogout }) {
  const [cameras, setCameras] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [health, setHealth] = useState(null)
  const [trust, setTrust] = useState(null)
  const [metrics, setMetrics] = useState(null)
  const [error, setError] = useState('')
  const [connected, setConnected] = useState(false)
  const [notice, setNotice] = useState('')
  const [showImport, setShowImport] = useState(false)
  const [viewing, setViewing] = useState(false)
  const [filter, setFilter] = useState('')

  async function refresh() {
    try {
      const [listed, counts] = await Promise.all([api('/cameras'),
        role === 'operator' ? api('/metrics') : Promise.resolve(null)])
      setCameras(listed); setMetrics(counts); setError(''); setConnected(true)
    }
    catch (cause) {
      setConnected(false)
      if (cause.message === 'Authentication required') onLogout()
      else setError(cause.message)
    }
  }
  useEffect(() => { refresh(); const timer = setInterval(refresh, 4000); return () => clearInterval(timer) }, [])
  useEffect(() => {
    if (!selectedId) { setHealth(null); setTrust(null); return }
    let live = true
    const read = () => api(`/cameras/${encodeURIComponent(selectedId)}/health`)
      .then(value => { if (live) setHealth(value) }).catch(cause => { if (live) setError(cause.message) })
    read(); const timer = setInterval(read, 2000)
    return () => { live = false; clearInterval(timer) }
  }, [selectedId])
  useEffect(() => {
    if (!selectedId) return
    let live = true
    const read = () => api(`/cameras/${encodeURIComponent(selectedId)}/trust`)
      .then(value => { if (live) setTrust(value) }).catch(cause => { if (live) setError(cause.message) })
    read(); const timer = setInterval(read, 5000)
    return () => { live = false; clearInterval(timer) }
  }, [selectedId])
  const selected = cameras.find(c => c.camera_id === selectedId)
  const shown = useMemo(() => cameras.filter(c =>
    `${c.camera_id} ${c.display_name} ${c.department}`.toLowerCase().includes(filter.toLowerCase())), [cameras, filter])
  const online = cameras.filter(c => c.health_status === 'online').length
  const government = cameras.filter(c => c.source_system === 'sentinel' && c.catalogue_present).length
  const active = metrics?.connected ?? 0

  async function sync() {
    setNotice('Refreshing Sentinel catalogue…')
    try {
      const result = await api('/cameras/sync-sentinel', {
        method: 'POST', headers: { 'X-CSRF-Token': csrf },
      })
      setNotice(`Catalogue: ${result.discovered} discovered, ${result.added} added, ${result.restored} restored, ${result.changed} changed, ${result.removed} removed.`)
      if (result.restart_ids.includes(selectedId)) setViewing(false)
      await refresh()
    } catch (cause) { setNotice(`Sync failed: ${cause.message}`) }
  }
  async function logout() {
    try { await api('/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': csrf } }) }
    finally { onLogout() }
  }
  async function deleteCamera(id, e) {
    e.stopPropagation()
    if (!confirm('Delete this camera?')) return
    try {
      await api(`/cameras/${encodeURIComponent(id)}`, { method: 'DELETE', headers: { 'X-CSRF-Token': csrf } })
      if (id === selectedId) { setSelectedId(null); setViewing(false) }
      await refresh()
    } catch (cause) { setError(cause.message) }
  }

  const select = useCallback((id) => { setSelectedId(id); setViewing(false) }, [])

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-icon">S</div><div><strong>SakhyaPath</strong><small>GUJARAT · OPERATIONS</small></div></div>
      <div className="side-nav"><span className="side-nav-icon" aria-hidden="true">▦</span><span>Camera grid</span><span className="nav-active-mark" /></div>
      <div className="side-section registry-summary"><span className="eyebrow">REGISTRY OVERVIEW</span>
        <div className="side-count">{cameras.length}<span> cameras mapped</span></div>
        <p>Live status is verified from decoded frames.</p>
        <div className="registry-progress"><span style={{ width: cameras.length ? `${Math.min(100, online / cameras.length * 100)}%` : '0%' }} /></div>
        <div className="registry-progress-label"><span>{online} verified live</span><span>{cameras.length - online} awaiting frames</span></div>
      </div>
      <div className="side-section camera-section"><div className="list-heading"><span className="eyebrow">CAMERA DIRECTORY</span><span>{shown.length}</span></div>
        <input className="search" aria-label="Search cameras" placeholder="Search ID, name, department" value={filter} onChange={e => setFilter(e.target.value)} />
        <div className="camera-list">{shown.length === 0 && <div className="camera-list-empty">No matching cameras</div>}{shown.map(c => <div key={c.camera_id} style={{display:'flex', alignItems:'center'}}>
          <button className={`camera-row ${selectedId === c.camera_id ? 'selected' : ''}`} onClick={() => select(c.camera_id)} style={{flex: 1}}>
          <span className={`status-dot ${c.health_status}`} /><span className="camera-row-text"><strong>{c.display_name}</strong>
          <small>{c.camera_id} · {c.department}</small></span></button>
          <button onClick={(e) => deleteCamera(c.camera_id, e)} className="quiet" style={{padding:'4px 8px', marginLeft:'4px'}} title="Delete">❌</button>
          </div>)}</div>
      </div>
      <div className="sidebar-actions"><button onClick={() => setShowImport(true)}><span aria-hidden="true">＋</span> Add owned camera</button>
        <button className="secondary" onClick={sync}><span aria-hidden="true">↻</span> Sync Sentinel catalogue</button></div>
      <div className="sidebar-foot"><span><i className="secure-dot" /> Read-only Sentinel</span><button className="quiet" onClick={logout}>Sign out ↗</button></div>
    </aside>
    <main className="main-area">
      <header className="topbar"><div><span className="eyebrow">OPERATIONS <span className="crumb-arrow">/</span> CAMERA GRID</span><h1>Camera intelligence <span className="heading-spark">✳</span></h1>
        <p>One clear view of every registered source and its verified state.</p></div>
        <div className="topbar-status"><span className={`pulse ${connected ? '' : 'unavailable'}`} />
          System {connected ? 'operational' : 'unavailable'}</div></header>
      {error && <div className="banner error" role="alert">{error}</div>}
      {notice && <div className="banner">{notice}</div>}
      <section className="hero-strip"><div><span className="hero-kicker">SAKHYAPATH / MODULE 01</span><h2>See the grid. Trust the signal.</h2>
        <p>Mapped infrastructure, source-aware preview, and health you can verify.</p></div><div className="hero-art" aria-hidden="true"><span /><span /><span /><i /></div></section>
      <section className="stats">
        <div className="stat-card"><div className="stat-top"><span>REGISTERED</span><i>▦</i></div><strong>{cameras.length}</strong><small>Mapped camera sources</small></div>
        <div className="stat-card"><div className="stat-top"><span>DECODED LIVE</span><i>◉</i></div><strong>{online}</strong><small>Verified video frames</small></div>
        <div className="stat-card"><div className="stat-top"><span>CAPTURE CONNECTED</span><i>⌁</i></div><strong>{active}</strong><small>{metrics?.viewed ?? 0} viewed · {metrics?.concurrently_analyzed ?? 0} analyzed</small></div>
        <div className="stat-card"><div className="stat-top"><span>SENTINEL LISTED</span><i>◇</i></div><strong>{government}</strong><small>Catalogue entries</small></div>
      </section>
      <div className="content-grid"><section className="panel map-panel"><div className="panel-head"><div><span className="eyebrow">GEOSPATIAL OVERVIEW</span><h2>Camera locations</h2></div>
        <span className="panel-tag">GUJARAT GRID</span></div>
        <CameraMap cameras={shown} selectedId={selectedId} onSelect={select} /></section>
        <section className="panel detail-panel"><div className="panel-head"><div><span className="eyebrow">SOURCE INSPECTOR</span><h2>{selected?.display_name || 'Select a camera'}</h2></div><span className="inspector-glyph" aria-hidden="true">↗</span></div>
          {selected ? <><div className="detail-meta"><div><span>Source</span><strong>{selected.source_mode.replaceAll('_', ' ')}</strong></div>
            <div><span>Feed health</span><strong>{selected.health_status}</strong></div>
            <div><span>Catalogue live</span><strong>{selected.catalogue_live == null ? 'N/A' : String(selected.catalogue_live)}</strong></div>
            <div><span>Codec</span><strong>{selected.codec || 'Unknown'}</strong></div></div>
            <div className="preview-frame">{viewing ? <CameraPreview key={selectedId} camera={selected} />
              : <div className="preview-empty"><span>◎</span><p>Preview is on standby.<br />Opening this feed starts a server-side capture.</p>
                <button onClick={() => setViewing(true)}>Open preview</button></div>}</div>
            {viewing && <button className="secondary stop" onClick={() => setViewing(false)}>Close preview</button>}
            <div className="timestamp"><span>Source PTS</span><strong>{health?.source_pts == null ? 'Not yet verified' : `${health.source_pts.toFixed(3)} s`}</strong>
              <small>Frame timing uses source PTS; receive time is only a health diagnostic.</small></div>
            <div className="trust-card"><span className="eyebrow">CAMERA + CLOCK TRUST</span>
              <strong>{trust?.readiness || 'Checking…'}</strong>
              <p>{trust?.shared_utc_verified ? 'Attested UTC for this stream generation' : 'Cross-camera timing approximate'}</p>
              <small>{trust?.measured_fps == null ? 'FPS unmeasured' : `${trust.measured_fps.toFixed(2)} measured fps`} · {trust?.capture_errors ?? 0} capture error(s) · queue {trust?.analysis_queue_age_ms == null ? 'unmeasured' : `${trust.analysis_queue_age_ms.toFixed(0)} ms`}</small>
              {trust?.pts_interval_stats && <p>PTS interval median {trust.pts_interval_stats.median_ms} ms · p95 {trust.pts_interval_stats.p95_ms} ms · {trust.pts_discontinuities_this_capture} discontinuities</p>}
              {(trust?.reasons || []).slice(0, 3).map(reason => <p key={reason}>◇ {reason}</p>)}
            </div>
            <div className="health-history"><span className="eyebrow">HEALTH HISTORY</span>
              {(health?.history || []).slice(0, 5).map((event, index) => <p key={`${event.at_utc}-${index}`}>
                <strong>{event.status}</strong><span>{new Date(event.at_utc).toLocaleString()}</span></p>)}</div>
          </> : <div className="empty-details"><span className="empty-glyph">◎</span><strong>Ready to inspect</strong><p>Choose a camera from the directory or map to view its source and health.</p></div>}
        </section></div>
      <IntelligencePanel csrf={csrf} selectedId={selectedId} role={role} />
      <JourneyPanel api={api} csrf={csrf} cameras={cameras} role={role} />
      <CaseBridgePanel api={api} csrf={csrf} cameras={cameras} role={role} department={department} />
      <div className="map-legend"><span><i className="status-dot online" /> Decoded live</span><span><i className="status-dot degraded" /> Degraded</span><span><i className="status-dot offline" /> Not verified</span></div>
      <footer><span>SAKHYAPATH · MODULES 01–04</span><span>Only decoded frames are marked online</span></footer>
    </main>
    {showImport && <ImportCamera csrf={csrf} onClose={() => setShowImport(false)} onDone={() => { setShowImport(false); refresh() }} />}
  </div>
}

function App() {
  const [auth, setAuth] = useState(null)
  const [loading, setLoading] = useState(true)
  const [startupError, setStartupError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 8000)
    api('/auth/me', { signal: controller.signal }).then(setAuth).catch(error => {
      if (error.name !== 'AbortError' && error.message !== 'Authentication required') {
        setStartupError('The server is temporarily unavailable. Sign in again shortly.')
      } else if (error.name === 'AbortError') {
        setStartupError('The server did not respond in time. Sign in again shortly.')
      }
    }).finally(() => { clearTimeout(timeout); setLoading(false) })
    return () => { clearTimeout(timeout); controller.abort() }
  }, [])
  if (loading) return <div className="loading">Opening SakhyaPath…</div>
  return auth ? <Dashboard csrf={auth.csrf_token} role={auth.role} department={auth.department} onLogout={() => setAuth(null)} />
    : <Login onLogin={setAuth} startupError={startupError} />
}

createRoot(document.getElementById('root')).render(<App />)
