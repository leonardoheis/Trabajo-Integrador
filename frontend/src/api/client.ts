import axios from 'axios'
import type { JobRecord, AuditEntry } from '../types'

const api = axios.create({
  baseURL: '/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
})

export async function uploadDocument(file: File): Promise<{ job_id: string }> {
  const formData = new FormData()
  formData.append('file', file)
  const response = await api.post<{ job_id: string }>('/documents/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return response.data
}

export async function getJobs(limit = 20, offset = 0): Promise<JobRecord[]> {
  const response = await api.get<JobRecord[]>('/jobs', {
    params: { limit, offset },
  })
  return response.data
}

export async function getJob(jobId: string): Promise<JobRecord> {
  const response = await api.get<JobRecord>(`/jobs/${jobId}`)
  return response.data
}

export async function getAuditLog(limit = 100): Promise<AuditEntry[]> {
  const response = await api.get<AuditEntry[]>('/audit', {
    params: { limit },
  })
  return response.data
}

export function createJobWebSocket(jobId: string): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const host = window.location.host
  return new WebSocket(`${protocol}://${host}/ws/jobs/${jobId}`)
}

export default api
