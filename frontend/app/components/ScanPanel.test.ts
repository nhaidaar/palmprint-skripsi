// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'

import { ScanPanel, scanFailureState } from './ScanPanel'

vi.mock('../lib/mediapipe', () => ({
  createHandLandmarker: async () => ({ handLandmarker: {
    detectForVideo: () => ({ landmarks: [[{ x: 0.5, y: 0.5 }]] }),
    close: vi.fn(),
  } }),
}))

it('keeps inactive debug previews blank or frozen while scanning with one live camera', async () => {
  const requests: Record<string, unknown>[] = []
  let frame: FrameRequestCallback = () => {}
  const stop = vi.fn()
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { frame = callback; return 1 })
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
  const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop }] })
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })
  vi.stubGlobal('fetch', vi.fn(async (path, init) => {
    if (path === '/api/status') return { ok: true, json: async () => ({
      app: { debug: true, camera_source: 'browser', dev_features: true },
    }) }
    const request = JSON.parse(init.body)
    requests.push(request)
    return { ok: true, json: async () => ({ status: 'DENIED', name: 'Unknown', direction: request.direction }) }
  }))
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    drawImage: vi.fn(), clearRect: vi.fn(), beginPath: vi.fn(), arc: vi.fn(), fill: vi.fn(),
  } as unknown as CanvasRenderingContext2D)
  const snapshot = vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL')
    .mockReturnValue('data:image/jpeg;base64,frame')
  const container = document.createElement('div')
  const root = createRoot(container)
  try {
    await act(async () => root.render(createElement(ScanPanel, { active: true })))
    const video = container.querySelector('video')!
    const group = container.querySelector('[aria-label="Browser camera direction"]')!
    expect(group).not.toBeNull()
    const [entry, exit] = Array.from(group.querySelectorAll('button'))
    expect(entry.getAttribute('aria-pressed')).toBe('true')
    expect(container.querySelector('[aria-label="Entry camera preview"]')?.contains(video)).toBe(true)
    const exitPreview = container.querySelector('[aria-label="Exit camera preview"]')!
    expect(exitPreview).not.toBeNull()
    expect(exitPreview.querySelector('video, img')).toBeNull()
    expect(exitPreview.textContent).toContain('Select Exit to preview')
    await act(async () => exit.click())
    expect(container.querySelector('[aria-label="Entry camera preview"]')?.textContent).toContain('Select Entry to preview')
    await act(async () => entry.click())
    Object.defineProperties(video, {
      videoWidth: { value: 640 }, videoHeight: { value: 480 }, readyState: { value: 2 },
    })
    await act(async () => (container.querySelector('#btnScan') as HTMLButtonElement).click())
    expect(requests[0]).toMatchObject({ direction: 'ENTRY', source: 'camera' })
    await act(async () => entry.click())
    expect(container.querySelector('#resultDisplay')).not.toBeNull()
    snapshot.mockReturnValue('data:image/jpeg;base64,entry-last-frame')
    await act(async () => exit.click())
    expect(exit.getAttribute('aria-pressed')).toBe('true')
    expect(entry.getAttribute('aria-pressed')).toBe('false')
    expect(container.querySelector('#resultDisplay')).toBeNull()
    expect(container.querySelector('[aria-label="Exit camera preview"]')?.contains(video)).toBe(true)
    expect((container.querySelector('[aria-label="Entry camera preview"]') as HTMLElement).style.order).toBe('0')
    expect((container.querySelector('[aria-label="Exit camera preview"]') as HTMLElement).style.order).toBe('1')
    expect(container.querySelector('img[alt="Entry last frame preview"]')?.getAttribute('src'))
      .toBe('data:image/jpeg;base64,entry-last-frame')
    expect(container.querySelector('[aria-label="Entry camera preview"]')?.textContent).toContain('Last frame')
    expect(container.querySelector('video')).toBe(video)
    await act(async () => (container.querySelector('#btnScan') as HTMLButtonElement).click())
    expect(requests[1]).toMatchObject({ direction: 'EXIT', source: 'camera' })
    await act(async () => frame(0))
    await act(async () => frame(900))
    expect(requests[2]).toMatchObject({ direction: 'EXIT', source: 'camera' })
    expect(container.querySelector('img[alt="Entry last frame preview"]')?.getAttribute('src'))
      .toBe('data:image/jpeg;base64,entry-last-frame')
    snapshot.mockReturnValue('data:image/jpeg;base64,exit-last-frame')
    await act(async () => entry.click())
    expect(container.querySelector('[aria-label="Entry camera preview"]')?.contains(video)).toBe(true)
    expect(container.querySelector('img[alt="Exit last frame preview"]')?.getAttribute('src'))
      .toBe('data:image/jpeg;base64,exit-last-frame')
    expect(container.querySelector('video')).toBe(video)
    expect(container.querySelectorAll('video')).toHaveLength(1)
    snapshot.mockImplementation(() => { throw new Error('Camera disconnected') })
    await act(async () => exit.click())
    expect(container.querySelector('[aria-label="Exit camera preview"]')?.contains(video)).toBe(true)
    expect(container.querySelector('[aria-label="Entry camera preview"]')?.textContent).toContain('Select Entry to preview')
    expect(getUserMedia).toHaveBeenCalledTimes(1)
  } finally {
    await act(async () => root.unmount())
    expect(stop).toHaveBeenCalledOnce()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  }
})

it('shows both USB cameras and identifies exit events without manual duplicate scans', async () => {
  const events: FakeEvents[] = []
  class FakeEvents {
    onmessage: ((event: { data: string }) => void) | null = null
    close = vi.fn()
    constructor(public url: string) { events.push(this) }
  }
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  vi.stubGlobal('EventSource', FakeEvents)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ app: { camera_source: 'usb' }, devices: {
      ENTRY: { camera_connected: 1 }, EXIT: { camera_connected: 0, last_error: 'Disconnected' },
    } }),
  }))
  const container = document.createElement('div')
  const root = createRoot(container)
  try {
    await act(async () => { root.render(createElement(ScanPanel, { active: true })) })
    expect(container.querySelector('img[alt="Entry camera preview"]')?.getAttribute('src')).toContain('direction=ENTRY')
    expect(container.querySelector('img[alt="Exit camera preview"]')?.getAttribute('src')).toContain('direction=EXIT')
    expect(events.map((event) => event.url)).toEqual([
      '/api/device-registration/scan-events?direction=ENTRY',
      '/api/device-registration/scan-events?direction=EXIT',
    ])
    await act(async () => {
      events[1].onmessage?.({ data: JSON.stringify({ stage: 'recognized', result: {
        direction: 'EXIT', name: 'Alice', status: 'ALLOWED', similarity: 0.95,
      } }) })
    })
    expect(container.textContent).toContain('EXIT')
    expect(container.textContent).toContain('Alice')
    expect(container.querySelector('#btnScan')).toBeNull()
    expect(container.querySelector('[aria-label="Browser camera direction"]')).toBeNull()
  } finally {
    await act(async () => root.unmount())
    expect(events.every((event) => event.close.mock.calls.length === 1)).toBe(true)
    vi.unstubAllGlobals()
  }
})

describe('scanFailureState', () => {
  it('clears stale result and maps no-hand errors to the static UI message', () => {
    expect(scanFailureState(new Error('No hand detected'), 'Scan failed')).toEqual({
      error: 'No hand detected — adjust position and try again',
      result: null,
      roiImage: '',
    })
  })

  it('keeps other scan error messages while clearing stale result', () => {
    expect(scanFailureState(new Error('Network error'), 'Scan failed')).toEqual({
      error: 'Network error',
      result: null,
      roiImage: '',
    })
  })
})
