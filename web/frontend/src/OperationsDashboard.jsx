import React, { useEffect, useState } from 'react'

/**
 * Operations Dashboard - Real-time pod activity monitoring
 * 
 * Shows:
 * - Queue depths for all pipeline stages
 * - Active sources being processed
 * - Recent errors
 * - County progress
 * - Processing velocity
 */
export default function OperationsDashboard() {
  const [queueStatus, setQueueStatus] = useState(null)
  const [recentActivity, setRecentActivity] = useState(null)
  const [activeSources, setActiveSources] = useState(null)
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let mounted = true
    let timer = null

    async function fetchData() {
      try {
        // Fetch all telemetry endpoints in parallel
        const [queueRes, activityRes, sourcesRes, healthRes] = await Promise.all([
          fetch('/api/telemetry/operations/queue-status'),
          fetch('/api/telemetry/operations/recent-activity?minutes=5'),
          fetch('/api/telemetry/operations/sources-being-processed?limit=10'),
          fetch('/api/telemetry/operations/health')
        ])

        if (!queueRes.ok || !activityRes.ok || !sourcesRes.ok || !healthRes.ok) {
          throw new Error('Failed to fetch operations telemetry')
        }

        const [queue, activity, sources, healthData] = await Promise.all([
          queueRes.json(),
          activityRes.json(),
          sourcesRes.json(),
          healthRes.json()
        ])

        if (mounted) {
          setQueueStatus(queue)
          setRecentActivity(activity)
          setActiveSources(sources)
          setHealth(healthData)
          setLoading(false)
          setError(null)
        }
      } catch (e) {
        if (mounted) {
          setError(e.message)
          setLoading(false)
        }
      }

      // Refresh every 10 seconds
      timer = setTimeout(fetchData, 10000)
    }

    fetchData()

    return () => {
      mounted = false
      if (timer) clearTimeout(timer)
    }
  }, [])

  if (loading) {
    return (
      <div style={{ padding: 20 }}>
        <h2>Operations Dashboard</h2>
        <p>Loading real-time pod activity...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ padding: 20 }}>
        <h2>Operations Dashboard</h2>
        <div style={{ color: 'crimson', padding: 10, background: '#fee' }}>
          Error: {error}
        </div>
      </div>
    )
  }

  const getHealthColor = (status) => {
    switch (status) {
      case 'healthy': return '#22c55e'
      case 'warning': return '#f59e0b'
      case 'error': return '#ef4444'
      default: return '#6b7280'
    }
  }

  return (
    <div style={{ padding: 20 }}>
      <h2>Operations Dashboard 📊</h2>
      <p style={{ color: '#666', fontSize: 14 }}>
        Real-time monitoring of crawler, processor, and API pods
      </p>

      {/* Health Status */}
      {health && (
        <div style={{
          padding: 16,
          marginTop: 20,
          background: '#fff',
          border: `2px solid ${getHealthColor(health.status)}`,
          borderRadius: 8
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{
              width: 12,
              height: 12,
              borderRadius: '50%',
              background: getHealthColor(health.status)
            }} />
            <h3 style={{ margin: 0 }}>
              System Health: {health.status.toUpperCase()}
            </h3>
          </div>
          {health.issues && health.issues.length > 0 && (
            <ul style={{ marginTop: 10, marginBottom: 0 }}>
              {health.issues.map((issue, i) => (
                <li key={i} style={{ color: '#ef4444' }}>{issue}</li>
              ))}
            </ul>
          )}
          <div style={{ marginTop: 10, fontSize: 12, color: '#666' }}>
            <div>Error Rate: {health.metrics.error_rate_pct}%</div>
            <div>Articles (last hour): {health.metrics.articles_last_hour}</div>
          </div>
        </div>
      )}

      {/* Queue Status */}
      {queueStatus && (
        <div style={{ marginTop: 20 }}>
          <h3>Pipeline Queues</h3>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: 16
          }}>
            <QueueCard
              title="Verification"
              count={queueStatus.verification_pending}
              description="URLs awaiting classification"
              icon="🔍"
            />
            <QueueCard
              title="Extraction"
              count={queueStatus.extraction_pending}
              description="Articles awaiting content extraction"
              icon="📄"
            />
            <QueueCard
              title="Analysis"
              count={queueStatus.analysis_pending}
              description="Articles awaiting ML classification"
              icon="🤖"
            />
            <QueueCard
              title="Entity Extraction"
              count={queueStatus.entity_extraction_pending}
              description="Articles awaiting gazetteer processing"
              icon="🗺️"
            />
          </div>
        </div>
      )}

      {/* Recent Activity */}
      {recentActivity && (
        <div style={{ marginTop: 20 }}>
          <h3>
            Processing Velocity
            <span style={{ fontSize: 14, fontWeight: 'normal', color: '#666' }}>
              {' '}(last {recentActivity.timeframe_minutes} minutes)
            </span>
          </h3>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: 16
          }}>
            <ActivityCard
              title="URLs Verified"
              count={recentActivity.urls_verified}
              rate={`${(recentActivity.urls_verified / recentActivity.timeframe_minutes).toFixed(1)}/min`}
            />
            <ActivityCard
              title="Articles Extracted"
              count={recentActivity.articles_extracted}
              rate={`${(recentActivity.articles_extracted / recentActivity.timeframe_minutes).toFixed(1)}/min`}
            />
            <ActivityCard
              title="Analysis Completed"
              count={recentActivity.analysis_completed}
              rate={`${(recentActivity.analysis_completed / recentActivity.timeframe_minutes).toFixed(1)}/min`}
            />
          </div>
        </div>
      )}

      {/* Active Sources */}
      {activeSources && activeSources.active_sources.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <h3>
            Currently Processing
            <span style={{ fontSize: 14, fontWeight: 'normal', color: '#666' }}>
              {' '}({activeSources.count} sources active)
            </span>
          </h3>
          <div style={{
            background: '#fff',
            border: '1px solid #e5e7eb',
            borderRadius: 8,
            overflow: 'hidden'
          }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: '#f9fafb', borderBottom: '1px solid #e5e7eb' }}>
                  <th style={tableHeaderStyle}>Source</th>
                  <th style={tableHeaderStyle}>County</th>
                  <th style={tableHeaderStyle}>Recent URLs</th>
                  <th style={tableHeaderStyle}>Pending</th>
                  <th style={tableHeaderStyle}>Articles</th>
                  <th style={tableHeaderStyle}>Last Activity</th>
                </tr>
              </thead>
              <tbody>
                {activeSources.active_sources.map((source, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid #e5e7eb' }}>
                    <td style={tableCellStyle}>
                      <div style={{ fontWeight: 500 }}>{source.name || source.host}</div>
                      <div style={{ fontSize: 12, color: '#666' }}>{source.host}</div>
                    </td>
                    <td style={tableCellStyle}>{source.county || '—'}</td>
                    <td style={tableCellStyle}>
                      <span style={{ fontWeight: 600 }}>{source.recent_urls}</span>
                    </td>
                    <td style={tableCellStyle}>{source.pending_verification}</td>
                    <td style={tableCellStyle}>{source.ready_for_extraction}</td>
                    <td style={tableCellStyle}>
                      <span style={{ fontSize: 12, color: '#666' }}>
                        {formatTimeAgo(source.last_activity)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div style={{ marginTop: 20, fontSize: 12, color: '#999', textAlign: 'right' }}>
        Auto-refreshing every 10 seconds
      </div>
    </div>
  )
}

function QueueCard({ title, count, description, icon }) {
  return (
    <div style={{
      padding: 16,
      background: '#fff',
      border: '1px solid #e5e7eb',
      borderRadius: 8
    }}>
      <div style={{ fontSize: 24, marginBottom: 8 }}>{icon}</div>
      <div style={{ fontSize: 12, color: '#666', marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: 28, fontWeight: 700, color: count > 0 ? '#3b82f6' : '#9ca3af' }}>
        {count.toLocaleString()}
      </div>
      <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>{description}</div>
    </div>
  )
}

function ActivityCard({ title, count, rate }) {
  return (
    <div style={{
      padding: 16,
      background: '#fff',
      border: '1px solid #e5e7eb',
      borderRadius: 8
    }}>
      <div style={{ fontSize: 12, color: '#666', marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color: '#22c55e' }}>
        {count.toLocaleString()}
      </div>
      <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>
        {rate}
      </div>
    </div>
  )
}

const tableHeaderStyle = {
  padding: '12px 16px',
  textAlign: 'left',
  fontSize: 12,
  fontWeight: 600,
  color: '#6b7280',
  textTransform: 'uppercase',
  letterSpacing: '0.5px'
}

const tableCellStyle = {
  padding: '12px 16px',
  fontSize: 14
}

function formatTimeAgo(isoString) {
  if (!isoString) return '—'
  
  const date = new Date(isoString)
  const now = new Date()
  const seconds = Math.floor((now - date) / 1000)
  
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}
