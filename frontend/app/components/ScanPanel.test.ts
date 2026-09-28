// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'

import { ScanPanel, scanFailureState } from './ScanPanel'

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
