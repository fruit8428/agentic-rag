// 地區設定（由後端 /api/auth/config 提供，來源是環境變數 DISTRICT_CODE / DISTRICT_NAME）。
// 全站共用一次抓取的結果；抓不到時用通用文字，畫面不會壞。
import { useEffect, useState } from 'react'
import { publicFetch } from './api'

export interface DistrictInfo {
  code: string
  name: string
  adminContact: string | null
}

const FALLBACK: DistrictInfo = { code: '', name: '扶輪地區', adminContact: null }
let cached: DistrictInfo | null = null
let pending: Promise<DistrictInfo> | null = null

export function fetchDistrict(): Promise<DistrictInfo> {
  if (cached) return Promise.resolve(cached)
  if (!pending) {
    pending = publicFetch<{ admin_contact: string | null; district_code?: string; district_name?: string }>('/api/auth/config')
      .then((c) => {
        cached = {
          code: c.district_code || '',
          name: c.district_name || FALLBACK.name,
          adminContact: c.admin_contact ?? null,
        }
        return cached
      })
      .catch(() => FALLBACK)
  }
  return pending
}

export function useDistrict(): DistrictInfo {
  const [info, setInfo] = useState<DistrictInfo>(cached || FALLBACK)
  useEffect(() => {
    let alive = true
    fetchDistrict().then((d) => {
      if (alive) setInfo(d)
    })
    return () => {
      alive = false
    }
  }, [])
  return info
}
