import { ChangeEvent, useEffect, useRef, useState } from 'react'

import { apiJson } from '../lib/api'
import { createHandLandmarker } from '../lib/mediapipe'

const SCAN_HOLD_MS = 800
const USB_PREVIEW_STREAM_URL = '/api/device-registration/preview.mjpg'

type Landmark = { x: number; y: number }

type RecognizeResult = {
  status?: string
  direction?: 'ENTRY' | 'EXIT' | null
  name?: string
  similarity?: number
  roi_image?: string
}

const NO_HAND_MESSAGE = 'No hand detected — adjust position and try again'

export function scanFailureState(err: unknown, fallback: string): { error: string; result: RecognizeResult | null; roiImage: string } {
  const message = err instanceof Error ? err.message : fallback
  return {
    error: /No hand detected|422/.test(message) ? NO_HAND_MESSAGE : message || fallback,
    result: null,
    roiImage: '',
  }
}

type ScanPanelProps = {
  active: boolean
}

function stripDataUrl(value: string) {
  return value.includes(',') ? value.split(',', 2)[1] : value
}

function drawHandOverlay(canvas: HTMLCanvasElement, video: HTMLVideoElement, landmarks: Landmark[]) {
  const width = video.videoWidth
  const height = video.videoHeight
  if (!width || !height) return
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.clearRect(0, 0, width, height)
  if (!landmarks.length) return
  ctx.fillStyle = '#22c55e'
  for (const point of landmarks) {
    ctx.beginPath()
    ctx.arc(point.x * width, point.y * height, 4, 0, Math.PI * 2)
    ctx.fill()
  }
}

export function ScanPanel({ active }: ScanPanelProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const overlayRef = useRef<HTMLCanvasElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const eventsRef = useRef<EventSource[]>([])
  const handLandmarkerRef = useRef<any>(null)
  const rafRef = useRef<number | null>(null)
  const holdStartRef = useRef<number | null>(null)
  const triggerScanRef = useRef<() => void>(() => {})
  const autoModeRef = useRef(true)
  const busyRef = useRef(false)
  const [usbDeviceMode, setUsbDeviceMode] = useState(false)
  const [devFeatures, setDevFeatures] = useState(false)
  const [direction, setDirection] = useState<'ENTRY' | 'EXIT'>('ENTRY')
  const [lastFrames, setLastFrames] = useState<Record<'ENTRY' | 'EXIT', string | null>>({ ENTRY: null, EXIT: null })
  const [autoMode, setAutoMode] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [guidance, setGuidance] = useState('Show your palm to the camera.')
  const [result, setResult] = useState<RecognizeResult | null>(null)
  const [scanStartedAt, setScanStartedAt] = useState<number | null>(null)
  const [roiImage, setRoiImage] = useState('')
  const [stats, setStats] = useState({ total: 0, allowed: 0, denied: 0, users: 0 })
  const [appVersion, setAppVersion] = useState('local')
  const [devices, setDevices] = useState<Record<string, { camera_connected?: number; last_error?: string }>>({})
  const inactiveDirection = direction === 'ENTRY' ? 'EXIT' : 'ENTRY'
  const activeLabel = usbDeviceMode || direction === 'ENTRY' ? 'Entry' : 'Exit'
  const inactiveLabel = usbDeviceMode || inactiveDirection === 'EXIT' ? 'Exit' : 'Entry'

  autoModeRef.current = autoMode
  busyRef.current = busy

  useEffect(() => {
    let cancelled = false
    let statusInterval: ReturnType<typeof setInterval> | undefined

    async function startCamera() {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true })
      if (cancelled) {
        stream.getTracks().forEach((track) => track.stop())
        return
      }
      streamRef.current = stream
      if (videoRef.current) videoRef.current.srcObject = stream
    }

    function detectLoop(ts: number) {
      rafRef.current = requestAnimationFrame(detectLoop)
      const video = videoRef.current
      const overlay = overlayRef.current
      const detector = handLandmarkerRef.current
      if (!video || !overlay || !detector || video.readyState < 2) return
      try {
        const detection = detector.detectForVideo(video, ts)
        const landmarks = detection.landmarks?.[0] ?? []
        drawHandOverlay(overlay, video, landmarks)
        const handFound = landmarks.length > 0
        setGuidance(handFound ? 'Palm detected. Hold still.' : 'Show your palm to the camera.')
        if (autoModeRef.current && handFound && !busyRef.current) {
          holdStartRef.current ??= ts
          if (ts - holdStartRef.current >= SCAN_HOLD_MS) {
            holdStartRef.current = null
            triggerScanRef.current()
          }
        } else {
          holdStartRef.current = null
        }
      } catch {
        setGuidance('Show your palm to the camera.')
      }
    }

    async function boot() {
      try {
        const data = await apiJson<any>('/api/status')
        if (cancelled) return
        const usb = data.app?.camera_source === 'usb'
        setUsbDeviceMode(usb)
        setDevFeatures(data.app?.dev_features === true)
        setAppVersion(data.app?.version ?? 'local')
        setStats((current) => ({ ...current, users: data.users?.total ?? current.users }))
        if (usb) {
          setDevices(data.devices ?? {})
          statusInterval = setInterval(async () => {
            try {
              const status = await apiJson<any>('/api/status')
              if (!cancelled) setDevices(status.devices ?? {})
            } catch {
              if (!cancelled) setDevices({})
            }
          }, 2000)
          eventsRef.current = ['ENTRY', 'EXIT'].map((direction) => {
            const events = new EventSource(`/api/device-registration/scan-events?direction=${direction}`)
            events.onmessage = (event) => {
              try {
                const data = JSON.parse(event.data)
                if (data.stage === 'recognized' && data.result) {
                  setResult(data.result)
                  setStats((current) => ({
                    ...current,
                    total: current.total + 1,
                    allowed: current.allowed + (data.result.status === 'ALLOWED' ? 1 : 0),
                    denied: current.denied + (data.result.status === 'DENIED' ? 1 : 0),
                  }))
                }
              } catch {
                setError('Could not read camera event')
              }
            }
            return events
          })
        } else {
          const { handLandmarker } = await createHandLandmarker()
          if (cancelled) {
            handLandmarker.close?.()
            return
          }
          handLandmarkerRef.current = handLandmarker
          await startCamera()
          if (cancelled) return
          rafRef.current = requestAnimationFrame(detectLoop)
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Manual scan mode')
      }
    }

    void boot()
    return () => {
      cancelled = true
      eventsRef.current.forEach((events) => events.close())
      clearInterval(statusInterval)
      streamRef.current?.getTracks().forEach((track) => track.stop())
      handLandmarkerRef.current?.close?.()
      handLandmarkerRef.current = null
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
    }
  }, [])

  function captureFrame(source: HTMLVideoElement | null) {
    if (!source || !canvasRef.current) throw new Error('No camera frame available')
    const width = source.videoWidth
    const height = source.videoHeight
    if (!width || !height) throw new Error('Camera is not ready')
    const canvas = canvasRef.current
    canvas.width = width
    canvas.height = height
    canvas.getContext('2d')?.drawImage(source, 0, 0, width, height)
    return stripDataUrl(canvas.toDataURL('image/jpeg', 0.9))
  }

  async function submitRecognitionImage(image: string, source = 'camera') {
    const started = performance.now()
    setScanStartedAt(started)
    const data = await apiJson<RecognizeResult>('/api/recognize', {
      method: 'POST',
      body: JSON.stringify({ image, is_roi: false, debug_roi: devFeatures, source, direction }),
    })
    setRoiImage(data.roi_image ?? '')
    setResult(data)
    setStats((current) => ({
      total: current.total + 1,
      allowed: current.allowed + (data.status === 'ALLOWED' ? 1 : 0),
      denied: current.denied + (data.status === 'DENIED' ? 1 : 0),
      users: current.users,
    }))
  }

  async function triggerScan() {
    if (busyRef.current || usbDeviceMode) return
    setBusy(true)
    setError('')
    try {
      await submitRecognitionImage(captureFrame(videoRef.current), 'camera')
    } catch (err) {
      const failure = scanFailureState(err, 'Scan failed')
      setError(failure.error)
      setResult(failure.result)
      setRoiImage(failure.roiImage)
    } finally {
      setBusy(false)
    }
  }

  triggerScanRef.current = () => { void triggerScan() }

  function selectDirection(next: 'ENTRY' | 'EXIT') {
    if (next === direction) return
    let snapshot: string | null = null
    try {
      if (videoRef.current && videoRef.current.readyState >= 2) {
        snapshot = `data:image/jpeg;base64,${captureFrame(videoRef.current)}`
      }
    } catch {
      // Keep the inactive preview blank if the camera cannot provide a frame.
    }
    setLastFrames((current) => ({ ...current, [direction]: snapshot }))
    setDirection(next)
    holdStartRef.current = null
    setResult(null)
    setRoiImage('')
    setError('')
    setScanStartedAt(null)
  }

  async function handleScanUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || busy) return
    setBusy(true)
    setError('')
    try {
      const dataUrl = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result))
        reader.onerror = () => reject(new Error('Failed to read image'))
        reader.readAsDataURL(file)
      })
      await submitRecognitionImage(stripDataUrl(dataUrl), 'upload')
    } catch (err) {
      const failure = scanFailureState(err, 'Upload scan failed')
      setError(failure.error)
      setResult(failure.result)
      setRoiImage(failure.roiImage)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className={`panel${active ? ' active' : ''}`} id="panel-scan">
      <div className="panel-grid">
        <div className="camera-col">
          <div className="camera-previews">
            <div className={`camera-frame${guidance.includes('detected') ? ' hand-detected' : ''}`} id="cameraFrame"
              role="group" aria-label={`${activeLabel} camera preview`}
              style={{ order: usbDeviceMode || direction === 'ENTRY' ? 0 : 1 }}>
              {usbDeviceMode ? (
                <img id="usbPreview" className="usb-preview" src={`${USB_PREVIEW_STREAM_URL}?direction=ENTRY`} alt="Entry camera preview" />
              ) : (
                <video ref={videoRef} id="video" autoPlay playsInline muted />
              )}
              <canvas ref={overlayRef} id="overlayCanvas" className="overlay-canvas" />
              <canvas ref={canvasRef} id="canvas" style={{ display: 'none' }} />
              <div className="autoscan-ring" id="autoscanRing" style={{ display: !usbDeviceMode && autoMode && !busy ? undefined : 'none' }}>
                <svg viewBox="0 0 100 100" className="ring-svg" aria-hidden="true">
                  <circle className="ring-track" cx="50" cy="50" r="42" />
                  <circle className="ring-fill" cx="50" cy="50" r="42" id="ringFill" />
                </svg>
                <span className="ring-label" id="ringLabel">Hold</span>
              </div>
              <div className="palm-guide" id="palmGuide">
                <div className="guide-ring outer" />
                <div className="guide-ring inner" />
                <div className="guide-label" id="guideLabel">Place palm here</div>
              </div>
              <div className="capture-flash" id="captureFlash" />
              <div className="brightness-badge" id="brightnessBadge" style={{ display: 'none' }} />
              <div className="camera-status" id="cameraStatus">
                <span className="cam-dot" />
                {usbDeviceMode ? 'Entry camera' : `${activeLabel} · ${error && !streamRef.current ? 'Camera offline' : 'Live'}`}
              </div>
            </div>

            <div className="camera-frame" role="group" aria-label={`${inactiveLabel} camera preview`}
              style={{ order: usbDeviceMode || inactiveDirection === 'EXIT' ? 1 : 0 }}>
              {usbDeviceMode ? (
                <img className="usb-preview" src={`${USB_PREVIEW_STREAM_URL}?direction=EXIT`} alt="Exit camera preview" />
              ) : lastFrames[inactiveDirection] ? (
                <img className="usb-preview" src={lastFrames[inactiveDirection]!} alt={`${inactiveLabel} last frame preview`} />
              ) : (
                <div className="camera-preview-empty">Select {inactiveLabel} to preview</div>
              )}
              <div className="camera-status">
                <span className={`cam-dot${usbDeviceMode ? '' : ' paused'}`} />
                {usbDeviceMode ? 'Exit camera' : `${inactiveLabel} · ${lastFrames[inactiveDirection] ? 'Last frame' : 'Waiting'}`}
              </div>
            </div>
          </div>
          {!usbDeviceMode && devFeatures && (
            <div className="scan-direction-controls" role="group" aria-label="Browser camera direction">
              <span>Debug input</span>
              {(['ENTRY', 'EXIT'] as const).map((role) => (
                <button className="btn btn-mode" type="button" key={role}
                  aria-pressed={direction === role} disabled={busy}
                  onClick={() => selectDirection(role)}>
                  {role === 'ENTRY' ? 'Entry' : 'Exit'}
                </button>
              ))}
            </div>
          )}
          <div className="scan-controls">
            {!usbDeviceMode && <>

            <button className="btn btn-primary btn-scan" id="btnScan" type="button" disabled={busy} onClick={() => void triggerScan()}>
              <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <path d="M10 2C5.582 2 2 5.582 2 10s3.582 8 8 8 8-3.582 8-8-3.582-8-8-8z" stroke="currentColor" strokeWidth="1.5" />
                <path d="M6 10l2.5 2.5L14 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Scan now
            </button>
            <button className="btn btn-mode" id="btnMode" type="button" aria-label="Toggle auto-detect mode" onClick={() => setAutoMode((value) => !value)}>
              {autoMode ? 'Auto' : 'Manual'}
            </button>
            </>}
            <label className="btn btn-secondary dev-only scan-upload-btn" id="scanUploadLabel" hidden={!devFeatures}>
              Upload photo
              <input className="scan-upload-input" id="scanUploadFile" type="file" accept="image/*" onChange={handleScanUpload} />
            </label>
          </div>
        </div>

        <div className="result-col">
          <div className={`result-card${result?.status === 'ALLOWED' ? ' allowed' : ''}${result?.status === 'DENIED' ? ' denied' : ''}`} id="resultCard">
            {!busy && !result && (
              <div className="result-idle" id="resultIdle">
                <div className="idle-icon" aria-hidden="true">◌</div>
                <p className="idle-text" id="idleText">Hold your open palm<br />in front of the camera</p>
                <div className="idle-hint" id="idleHint">{autoMode ? 'Auto-detect on' : 'Manual mode'}</div>
                {error && <p className="idle-text">{error}</p>}
              </div>
            )}
            {!busy && result && (
              <div className="result-display" id="resultDisplay">
                <div className="result-badge">
                  <div className="badge-icon" id="badgeIcon">{result.status === 'ALLOWED' ? '✓' : '×'}</div>
                  <div className={`badge-status ${result.status === 'ALLOWED' ? 'allowed' : 'denied'}`} id="badgeStatus">{result.status ?? 'DONE'}</div>
                </div>
                <div className={`result-name ${result.status === 'ALLOWED' ? 'allowed' : 'denied'}`} id="resultName">{result.name ?? 'Unknown palm'}</div>
                <div className="result-meta">
                  {result.direction && <div className="meta-row"><span className="meta-label">Direction</span><span className="meta-value">{result.direction}</span></div>}
                  <div className="meta-row" id="timingRow" style={{ display: scanStartedAt == null ? 'none' : undefined }}>
                    <span className="meta-label">Identified in</span>
                    <span className="meta-value meta-timing" id="resultTiming">{scanStartedAt == null ? '—' : `${Math.round(performance.now() - scanStartedAt)} ms`}</span>
                  </div>
                  <div className="meta-row">
                    <span className="meta-label">Similarity</span>
                    <span className="meta-value" id="resultSimilarity">{result.similarity == null ? '—' : `${Math.round(result.similarity * 100)}%`}</span>
                  </div>
                  <div className="meta-row" id="closestRow" style={{ display: 'none' }}>
                    <span className="meta-label">Closest match</span>
                    <span className="meta-value" id="resultClosest">—</span>
                  </div>
                  <div className="meta-row">
                    <span className="meta-label">At</span>
                    <span className="meta-value" id="resultTimestamp">{new Date().toLocaleTimeString()}</span>
                  </div>
                </div>
                <div className="roi-preview dev-only" id="roiPreview" hidden={!devFeatures || !roiImage}>
                  <div className="roi-preview-label">ROI used for embedding</div>
                  <img id="roiPreviewImage" src={roiImage || undefined} alt="Processed palm ROI used for recognition" />
                </div>
              </div>
            )}
            {busy && (
              <div className="result-scanning" id="resultScanning">
                <div className="scan-animation"><div className="scan-line" /></div>
                <p className="scanning-text">Analyzing palmprint…</p>
              </div>
            )}
          </div>

          <div className="device-status-card" id="deviceStatusCard">
            <div className="device-status-row"><span>Version</span><strong id="appVersion">{appVersion}</strong></div>
            <div className="device-status-row"><span>Mode</span><strong>{usbDeviceMode ? 'Non-debug · USB' : 'Debug · Browser'}</strong></div>
            {devFeatures && <div className="device-status-row"><span>GPIO</span><strong>Disabled in debug</strong></div>}
            <div className="device-status-row"><span>Worker</span><strong id="deviceWorkerState">{usbDeviceMode ? 'enabled' : 'disabled'}</strong></div>
            {usbDeviceMode ? ['ENTRY', 'EXIT'].map((direction) => (
              <div className="device-status-row" key={direction}>
                <span>{direction === 'ENTRY' ? 'Entry camera' : 'Exit camera'}</span>
                <strong title={devices[direction]?.last_error}>{devices[direction]?.camera_connected ? 'online' : 'offline'}</strong>
              </div>
            )) : <div className="device-status-row"><span>Camera</span><strong id="deviceCameraState">{error ? 'offline' : 'online'}</strong></div>}
            <div className="device-status-row"><span>FPS</span><strong id="deviceFps">—</strong></div>
            <div className="device-status-row"><span>Last recognition</span><strong id="deviceLastRecognition">{result?.status ?? '—'}</strong></div>
          </div>

          <div className="mini-stats">
            <div className="stat-item"><span className="stat-num" id="statTotal">{stats.total}</span><span className="stat-label">Total</span></div>
            <div className="stat-divider" />
            <div className="stat-item"><span className="stat-num" id="statAllowed">{stats.allowed}</span><span className="stat-label">Allowed</span></div>
            <div className="stat-divider" />
            <div className="stat-item"><span className="stat-num" id="statDenied">{stats.denied}</span><span className="stat-label">Denied</span></div>
            <div className="stat-divider" />
            <div className="stat-item"><span className="stat-num" id="statUsers">{stats.users}</span><span className="stat-label">Enrolled</span></div>
          </div>
        </div>
      </div>
    </section>
  )
}
