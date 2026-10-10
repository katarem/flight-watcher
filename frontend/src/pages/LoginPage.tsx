import { useQueryClient } from '@tanstack/react-query'
import { Plane } from 'lucide-react'
import { motion } from 'motion/react'
import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router'
import { errorList, post } from '@/api/client'
import { keys, useMe } from '@/api/queries'
import type { Me } from '@/api/types'
import { Button } from '@/components/ui/button'
import { ErrorBox } from '@/components/ui/feedback'
import { Field, Input } from '@/components/ui/form'
import { useTitle } from '@/lib/hooks'

/** Solo rutas internas: evita que ?next=https://otro.sitio sirva de redirección abierta. */
const safeNext = (v: string | null) => (v && v.startsWith('/') && !v.startsWith('//') && !v.startsWith('/\\') ? v : '/')

export function LoginPage() {
  useTitle('Iniciar sesión')
  const me = useMe()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  if (me.data) return <Navigate to={next} replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setErrors([])
    try {
      const { user } = await post<{ user: Me }>('/session', { username, password })
      qc.setQueryData(keys.me, user)
      navigate(next, { replace: true })
    } catch (err) {
      setErrors(errorList(err))
      setBusy(false)
    }
  }

  return (
    <main className="relative grid min-h-dvh place-items-center overflow-hidden px-4">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute -top-40 left-1/2 size-[36rem] -translate-x-1/2 rounded-full bg-accent/15 blur-3xl" />
        <div className="absolute -bottom-48 -left-24 size-[28rem] rounded-full bg-deal/10 blur-3xl" />
      </div>
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: 'easeOut' }}
        className="w-full max-w-sm"
      >
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <motion.span
            initial={{ x: -40, y: 20, rotate: -45, opacity: 0 }}
            animate={{ x: 0, y: 0, rotate: -45, opacity: 1 }}
            transition={{ type: 'spring', bounce: 0.35, duration: 0.8, delay: 0.1 }}
            className="grid size-14 place-items-center rounded-2xl bg-accent text-accent-fg shadow-lg shadow-accent/30"
          >
            <Plane className="size-7" aria-hidden="true" />
          </motion.span>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Flight Watcher</h1>
            <p className="text-sm text-fg/80">Vigila precios de vuelos y te avisa de los chollos.</p>
          </div>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-2xl border border-line bg-surface p-6 shadow-card" noValidate>
          <ErrorBox errors={errors} />
          <Field label="Usuario">
            {(id) => (
              <Input id={id} value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username"
                autoCapitalize="none" required autoFocus />
            )}
          </Field>
          <Field label="Contraseña">
            {(id) => (
              <Input id={id} type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password" required />
            )}
          </Field>
          <Button type="submit" className="w-full" loading={busy}>Entrar</Button>
        </form>
      </motion.div>
    </main>
  )
}
