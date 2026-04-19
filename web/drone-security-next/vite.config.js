import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import net from 'node:net'

function attackBridgePlugin() {
  let telemetryClient = null
  let telemetryBuffer = ''
  let latestTelemetry = null
  const sseClients = new Set()

  function broadcastTelemetry(payload) {
    const frame = `data: ${JSON.stringify(payload)}\n\n`
    for (const client of sseClients) {
      client.write(frame)
    }
  }

  function attachTelemetryClient() {
    if (telemetryClient && !telemetryClient.destroyed) return

    telemetryClient = net.createConnection({ host: '127.0.0.1', port: 9998 })

    telemetryClient.on('data', (chunk) => {
      telemetryBuffer += chunk.toString('utf-8')
      const lines = telemetryBuffer.split('\n')
      telemetryBuffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.trim()) continue
        try {
          latestTelemetry = JSON.parse(line)
          broadcastTelemetry(latestTelemetry)
        } catch {
          // ignore malformed telemetry frames
        }
      }
    })

    telemetryClient.on('error', () => {
      setTimeout(attachTelemetryClient, 1200)
    })

    telemetryClient.on('close', () => {
      setTimeout(attachTelemetryClient, 1200)
    })
  }

  return {
    name: 'attack-bridge',
    configureServer(server) {
      attachTelemetryClient()

      server.middlewares.use('/api/telemetry', (req, res) => {
        if (req.method !== 'GET') {
          res.statusCode = 405
          res.setHeader('Content-Type', 'application/json; charset=utf-8')
          res.end(JSON.stringify({ ok: false, error: 'Method Not Allowed' }))
          return
        }

        res.statusCode = 200
        res.setHeader('Content-Type', 'application/json; charset=utf-8')
        res.end(JSON.stringify({ ok: true, data: latestTelemetry }))
      })

      server.middlewares.use('/api/telemetry/stream', (req, res) => {
        if (req.method !== 'GET') {
          res.statusCode = 405
          res.setHeader('Content-Type', 'application/json; charset=utf-8')
          res.end(JSON.stringify({ ok: false, error: 'Method Not Allowed' }))
          return
        }

        res.statusCode = 200
        res.setHeader('Content-Type', 'text/event-stream; charset=utf-8')
        res.setHeader('Cache-Control', 'no-cache, no-transform')
        res.setHeader('Connection', 'keep-alive')
        res.write('retry: 1500\n\n')

        if (latestTelemetry) {
          res.write(`data: ${JSON.stringify(latestTelemetry)}\n\n`)
        }

        sseClients.add(res)
        req.on('close', () => {
          sseClients.delete(res)
        })
      })

      server.middlewares.use('/api/attack', (req, res) => {
        if (req.method !== 'POST') {
          res.statusCode = 405
          res.setHeader('Content-Type', 'application/json; charset=utf-8')
          res.end(JSON.stringify({ ok: false, error: 'Method Not Allowed' }))
          return
        }

        let body = ''
        req.on('data', (chunk) => {
          body += chunk
        })

        req.on('end', () => {
          try {
            const { cmd } = JSON.parse(body || '{}')
            if (!cmd || typeof cmd !== 'string') {
              res.statusCode = 400
              res.setHeader('Content-Type', 'application/json; charset=utf-8')
              res.end(JSON.stringify({ ok: false, error: 'Invalid command' }))
              return
            }

            const client = net.createConnection({ host: '127.0.0.1', port: 9999 }, () => {
              client.write(cmd)
              client.end()
            })

            client.on('error', (error) => {
              res.statusCode = 502
              res.setHeader('Content-Type', 'application/json; charset=utf-8')
              res.end(JSON.stringify({ ok: false, error: `Bridge failed: ${error.message}` }))
            })

            client.on('close', () => {
              if (res.writableEnded) return
              res.statusCode = 200
              res.setHeader('Content-Type', 'application/json; charset=utf-8')
              res.end(JSON.stringify({ ok: true, cmd }))
            })
          } catch (error) {
            res.statusCode = 400
            res.setHeader('Content-Type', 'application/json; charset=utf-8')
            res.end(JSON.stringify({ ok: false, error: `Bad request: ${error.message}` }))
          }
        })
      })
    },
  }
}

export default defineConfig({
  plugins: [vue(), attackBridgePlugin()],
  build: {
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/echarts')) return 'echarts'
          if (id.includes('node_modules/vue')) return 'vue'
          return undefined
        },
      },
    },
  },
})
