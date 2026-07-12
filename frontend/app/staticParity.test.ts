import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { Dashboard } from './routes/index'

function renderDashboard() {
  return renderToStaticMarkup(createElement(Dashboard))
}

describe('dashboard static UI parity', () => {
  it('renders the static header and four-tab navigation shell', () => {
    const html = renderDashboard()
    const nav = html.slice(html.indexOf('<nav'), html.indexOf('</nav>'))

    expect(html).toContain('class="header"')
    expect(html).toContain('class="header-left"')
    expect(html).toContain('class="logo-mark"')
    expect(html).toContain('class="brand-name"')
    expect(html).toContain('PalmGate')
    expect(html).toContain('Biometric access')
    expect(html).toContain('class="nav"')
    expect(html).toContain('class="nav-btn active"')
    expect(nav).toContain('data-tab="scan"')
    expect(nav).toContain('data-tab="register"')
    expect(nav).toContain('data-tab="log"')
    expect(nav).toContain('data-tab="user"')
    expect(nav.indexOf('data-tab="scan"')).toBeLessThan(nav.indexOf('data-tab="register"'))
    expect(nav.indexOf('data-tab="register"')).toBeLessThan(nav.indexOf('data-tab="log"'))
    expect(nav.indexOf('data-tab="log"')).toBeLessThan(nav.indexOf('data-tab="user"'))
    expect(html).toContain('class="main"')
  })

  it('renders the static scan panel structure', () => {
    const html = renderDashboard()

    expect(html).toContain('id="panel-scan"')
    expect(html).toContain('class="panel active"')
    expect(html).toContain('class="panel-grid"')
    expect(html).toContain('id="cameraFrame"')
    expect(html).toContain('class="overlay-canvas"')
    expect(html).toContain('id="autoscanRing"')
    expect(html).toContain('class="scan-controls"')
    expect(html).toContain('id="resultCard"')
    expect(html).toContain('id="deviceStatusCard"')
    expect(html).toContain('class="mini-stats"')
  })

  it('renders the static registration panel structure', () => {
    const html = renderDashboard()

    expect(html).toContain('id="panel-register"')
    expect(html).toContain('class="register-layout unified"')
    expect(html).toContain('id="regCameraFrame"')
    expect(html).toContain('id="handGuideOverlay"')
    expect(html).toContain('class="guidance-metrics"')
    expect(html).toContain('id="registrationModeTabs"')
    expect(html).toContain('id="cameraRegistrationPanel"')
    expect(html).toContain('id="uploadRegistrationPanel"')
    expect(html).toContain('id="captureDots"')
    expect(html).toContain('id="registerFeedback"')
  })

  it('renders the static log panel structure', () => {
    const html = renderDashboard()

    expect(html).toContain('id="panel-log"')
    expect(html).toContain('class="log-header"')
    expect(html).toContain('class="log-table-wrap"')
    expect(html).toContain('id="logTableBody"')
    expect(html).toContain('id="logPagination"')
    expect(html).toContain('id="btnLogPrev"')
    expect(html).toContain('id="btnLogNext"')
    expect(html).toContain('Export Excel')
    expect(html).toContain('aria-label="Access log filters"')
    expect(html).toContain('Search name, NIM, or description')
    expect(html).toContain('Results and Excel export use the same active filters')
  })

  it('renders the dedicated user management table structure', () => {
    const html = renderDashboard()

    expect(html).toContain('id="panel-user"')
    expect(html).toContain('class="users-section"')
    expect(html).toContain('class="users-table-wrap"')
    expect(html).toContain('class="users-table"')
    expect(html).toContain('id="usersTableBody"')
    expect(html).toContain('<th>NIM</th>')
    expect(html).toContain('<th>Name</th>')
    expect(html).toContain('<th>Registered</th>')
    expect(html).toContain('<th>Actions</th>')
    expect(html).toContain('Enrolled users')
  })

  it('renders API loading states', () => {
    const html = renderDashboard()

    expect(html).toContain('Loading access log…')
    expect(html).toContain('Loading users…')
  })
})
