// 統一的後端 API 呼叫工具：自動帶上登入 token，並把後端的 detail 錯誤訊息轉成 Error
export async function apiFetch<T>(
  path: string,
  accessToken: string,
  init: RequestInit = {}
): Promise<T> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${accessToken}`,
    ...(init.headers as Record<string, string> | undefined),
  }
  if (init.body && !(init.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json'
  }
  const res = await fetch(path, { ...init, headers })
  const text = await res.text()
  let data: any = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = null
  }
  if (!res.ok) {
    const detail = data?.detail
    throw new Error(typeof detail === 'string' ? detail : `請求失敗（HTTP ${res.status}）`)
  }
  return data as T
}

export interface MyClub {
  user_id: string
  email: string
  role: 'member' | 'admin'
  club_id: string | null
  club_name: string | null
}

export interface ClubPublic {
  id: string
  name: string
  division: string | null
  code: string | null
  joinable: boolean
}
