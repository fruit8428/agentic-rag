import { createClient } from '@supabase/supabase-js'

const DEFAULT_SUPABASE_URL = 'https://rrjbfgvfawjthrknvnls.supabase.co'
const DEFAULT_SUPABASE_ANON_KEY =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJyamJmZ3ZmYXdqdGhya252bmxzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTIxNDAzNTAsImV4cCI6MjEwNzcxNjM1MH0.-K5wEED6Dos8rJr5be_IL8BoVxs45GvZI32-Mo5Tayc'

const supabaseUrl = (
  import.meta.env.VITE_SUPABASE_URL ||
  import.meta.env.SUPABASE_URL ||
  DEFAULT_SUPABASE_URL
) as string

const supabaseAnonKey = (
  import.meta.env.VITE_SUPABASE_ANON_KEY ||
  import.meta.env.SUPABASE_ANON_KEY ||
  DEFAULT_SUPABASE_ANON_KEY
) as string

export const supabase = createClient(supabaseUrl, supabaseAnonKey)

