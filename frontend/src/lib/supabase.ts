import { createClient } from '@supabase/supabase-js'

const DEFAULT_SUPABASE_URL = 'https://rrjbfgvfawjthrknvnls.supabase.co'
const DEFAULT_SUPABASE_ANON_KEY =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJyamJmZ3ZmYXdqdGhya252bmxzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTIxNDAzNTAsImV4cCI6MjEwNzcxNjM1MH0.-K5wEED6Dos8rJr5be_IL8BoVxs45GvZI32-Mo5Tayc'

const rawUrl = (import.meta.env.VITE_SUPABASE_URL || import.meta.env.SUPABASE_URL || '') as string
const rawKey = (import.meta.env.VITE_SUPABASE_ANON_KEY || import.meta.env.SUPABASE_ANON_KEY || '') as string

const supabaseUrl = rawUrl.startsWith('https://') ? rawUrl.trim() : DEFAULT_SUPABASE_URL
const supabaseAnonKey =
  rawKey.trim().length > 100 && rawKey.trim().split('.').length === 3
    ? rawKey.trim()
    : DEFAULT_SUPABASE_ANON_KEY

export const supabase = createClient(supabaseUrl, supabaseAnonKey)


