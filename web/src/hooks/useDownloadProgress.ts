/**
 * SSE 进度订阅 Hook
 */

import { useEffect, useRef, useState } from 'react'

import { subscribeProgress } from '@/api/download'
import type { ProgressEvent } from '@/api/client'

export function useDownloadProgress(taskId: string | null): {
  events: ProgressEvent[]
  lastEvent: ProgressEvent | null
  isConnected: boolean
  clear: () => void
} {
  const [events, setEvents] = useState<ProgressEvent[]>([])
  const [lastEvent, setLastEvent] = useState<ProgressEvent | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const eventsRef = useRef<ProgressEvent[]>([])

  useEffect(() => {
    if (!taskId) {
      setEvents([])
      setLastEvent(null)
      eventsRef.current = []
      return
    }

    setEvents([])
    eventsRef.current = []
    setIsConnected(true)

    const unsubscribe = subscribeProgress(taskId, (event) => {
      setLastEvent(event)
      eventsRef.current = [...eventsRef.current, event]
      setEvents(eventsRef.current)
    })

    return () => {
      unsubscribe()
      setIsConnected(false)
    }
  }, [taskId])

  return {
    events,
    lastEvent,
    isConnected,
    clear: () => {
      setEvents([])
      eventsRef.current = []
    },
  }
}
