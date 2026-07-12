import { request } from 'node:http'

import { tanstackStart } from '@tanstack/react-start/plugin/vite'
import viteReact from '@vitejs/plugin-react'
import { nitro } from 'nitro/vite'
import { defineConfig, type Plugin } from 'vite'

function palmgateApiProxy(): Plugin {
  return {
    name: 'palmgate-api-proxy',
    enforce: 'pre',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = req.originalUrl ?? req.url ?? ''
        if (!url.startsWith('/api')) return next()

        const target = new URL(url, 'http://127.0.0.1:8000')
        const proxyRequest = request(target, {
          method: req.method,
          headers: { ...req.headers, host: target.host },
        }, (proxyResponse) => {
          res.writeHead(proxyResponse.statusCode ?? 502, proxyResponse.headers)
          proxyResponse.pipe(res)
        })

        proxyRequest.on('error', (error) => {
          if (!res.headersSent) res.writeHead(502, { 'content-type': 'text/plain' })
          res.end(`API proxy failed: ${error.message}`)
        })

        req.pipe(proxyRequest)
      })
    },
  }
}

export default defineConfig({
  server: {
    host: '127.0.0.1',
    port: 3000,
  },
  resolve: {
    tsconfigPaths: true,
  },
  plugins: [
    palmgateApiProxy(),
    tanstackStart({
      srcDirectory: 'app',
    }),
    viteReact(),
    nitro(),
  ],
})
