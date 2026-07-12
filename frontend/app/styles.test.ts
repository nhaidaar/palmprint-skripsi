import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const normalizeCss = (value: string) => value.replace(/\r\n/g, '\n').trim()

describe('dashboard stylesheet parity', () => {
  it('matches app/static/style.css exactly', () => {
    const frontendCss = readFileSync(join(import.meta.dirname, 'styles.css'), 'utf8')
    const staticCss = readFileSync(resolve(import.meta.dirname, '../../app/static/style.css'), 'utf8')

    expect(normalizeCss(frontendCss)).toBe(normalizeCss(staticCss))
  })

  it('includes user table styles and keeps static user actions in sync', () => {
    const css = readFileSync(join(import.meta.dirname, 'styles.css'), 'utf8')
    const staticJs = readFileSync(resolve(import.meta.dirname, '../../app/static/app.js'), 'utf8')

    expect(css).toContain('.users-table-wrap')
    expect(css).toContain('.users-table')
    expect(css).toContain('.user-table-actions')
    expect(css).toContain('.user-action-btn')
    expect(staticJs).toContain('users-table')
    expect(staticJs).toContain('user-action-btn danger')
    expect(staticJs).not.toContain('user-chip')
  })

  it('includes polished log filter styles', () => {
    const css = readFileSync(join(import.meta.dirname, 'styles.css'), 'utf8')

    expect(css).toContain('.log-filters')
    expect(css).toContain('.log-filter-label')
    expect(css).toContain('.log-search-wrap')
    expect(css).toContain('.log-filter-hint')
    expect(css).toContain('.btn-spinner')
  })
})
