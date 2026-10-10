import { useQueryClient } from '@tanstack/react-query'
import { Dialog } from 'radix-ui'
import {
  Activity, Bug, History, LayoutDashboard, LogOut, Menu as MenuIcon, Monitor, Moon, Play, Plane, Settings, Sun, User as UserIcon,
  Users, X,
} from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router'
import { Toaster } from 'sonner'
import { del } from '@/api/client'
import { keys, useMe, useMeta, useStatus } from '@/api/queries'
import { Avatar } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/feedback'
import { Menu, MenuContent, MenuItem, MenuLabel, MenuRadio, MenuSeparator, MenuTrigger } from '@/components/ui/menu'
import { cn } from '@/lib/cn'
import { fmtDateTime } from '@/lib/format'
import { useRunNow } from '@/lib/hooks'
import { useThemePref } from '@/lib/theme-context'

interface NavItem {
  to: string
  label: string
  icon: React.ReactNode
  end?: boolean
}

function useNavItems(): NavItem[] {
  const me = useMe().data
  const items: NavItem[] = [
    { to: '/', label: 'Panel', icon: <LayoutDashboard />, end: true },
    { to: '/runs', label: 'Ejecuciones', icon: <History /> },
  ]
  if (me?.role === 'admin')
    items.push(
      { to: '/admin/users', label: 'Usuarios', icon: <Users /> },
      { to: '/admin/providers', label: 'Proveedores', icon: <Activity /> },
      { to: '/settings', label: 'Ajustes', icon: <Settings /> },
      { to: '/debug', label: 'Diagnóstico', icon: <Bug /> },
    )
  return items
}

function DesktopNav() {
  return (
    <nav aria-label="Principal" className="hidden items-center gap-1 md:flex">
      {useNavItems().map((it) => (
        <NavLink
          key={it.to}
          to={it.to}
          end={it.end}
          className={({ isActive }) =>
            cn('relative rounded-lg px-3 py-1.5 text-sm font-medium transition-colors', isActive ? 'text-fg' : 'text-muted hover:text-fg')
          }
        >
          {({ isActive }) => (
            <>
              {isActive && (
                <motion.span
                  layoutId="nav-pill"
                  className="absolute inset-0 rounded-lg bg-surface-2"
                  transition={{ type: 'spring', bounce: 0.2, duration: 0.4 }}
                />
              )}
              <span className="relative">{it.label}</span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  )
}

function MobileNav() {
  const [open, setOpen] = useState(false)
  const items = useNavItems()
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <Button variant="ghost" size="icon" className="md:hidden" aria-label="Abrir menú">
          <MenuIcon />
        </Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm data-[state=open]:animate-[fade-in_150ms_ease-out]" />
        <Dialog.Content className="fixed inset-x-3 top-3 z-50 rounded-2xl border border-line bg-surface p-3 shadow-2xl data-[state=open]:animate-[slide-down_200ms_ease-out]">
          <div className="mb-2 flex items-center justify-between px-2">
            <Dialog.Title className="text-sm font-semibold">Menú</Dialog.Title>
            <Dialog.Close asChild>
              <Button variant="ghost" size="icon" aria-label="Cerrar menú"><X /></Button>
            </Dialog.Close>
          </div>
          <Dialog.Description className="sr-only">Secciones del panel</Dialog.Description>
          <nav aria-label="Principal" className="grid gap-1">
            {items.map((it) => (
              <NavLink
                key={it.to}
                to={it.to}
                end={it.end}
                onClick={() => setOpen(false)}
                className={({ isActive }) =>
                  cn('flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium [&_svg]:size-4',
                    isActive ? 'bg-accent-soft text-accent' : 'text-fg hover:bg-surface-2')
                }
              >
                {it.icon}
                {it.label}
              </NavLink>
            ))}
          </nav>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

function UserMenu() {
  const me = useMe().data!
  const [theme, setTheme] = useThemePref()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const logout = async () => {
    await del('/session').catch(() => {})
    qc.clear()
    qc.setQueryData(keys.me, null)
    navigate('/login')
  }
  return (
    <Menu>
      <MenuTrigger asChild>
        <button
          type="button"
          className="flex items-center gap-2 rounded-full p-0.5 pr-0.5 transition hover:bg-surface-2 sm:pr-3"
          aria-label={`Menú de ${me.display_name}`}
        >
          <Avatar user={me} size="sm" />
          <span className="hidden max-w-36 truncate text-sm font-medium sm:inline">{me.display_name}</span>
        </button>
      </MenuTrigger>
      <MenuContent>
        <MenuLabel>
          @{me.username}
          {me.role === 'admin' && ' · administrador'}
        </MenuLabel>
        <MenuItem asChild>
          <Link to="/profile"><UserIcon /> Mi perfil</Link>
        </MenuItem>
        <MenuSeparator />
        <MenuLabel>Tema</MenuLabel>
        <MenuRadio
          value={theme}
          onChange={setTheme}
          options={[
            { value: 'system', label: 'Como el sistema', icon: <Monitor /> },
            { value: 'light', label: 'Claro', icon: <Sun /> },
            { value: 'dark', label: 'Oscuro', icon: <Moon /> },
          ]}
        />
        <MenuSeparator />
        <MenuItem onSelect={logout}>
          <LogOut /> Cerrar sesión
        </MenuItem>
      </MenuContent>
    </Menu>
  )
}

function RunningBanner() {
  const status = useStatus().data
  return (
    <AnimatePresence>
      {status?.running && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          className="overflow-hidden border-b border-accent/20 bg-accent-soft"
          role="status"
          aria-live="polite"
        >
          <div className="mx-auto flex max-w-6xl items-center gap-2 px-4 py-2 text-sm text-accent">
            <Spinner className="size-4" />
            <span className="font-medium">Comprobando precios…</span>
            {status.current && <span className="truncate text-accent/80">{status.current}</span>}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export function AppShell() {
  const meta = useMeta().data
  const status = useStatus().data
  const run = useRunNow()
  const [theme] = useThemePref()
  const loc = useLocation()
  const main = useRef<HTMLElement>(null)
  const first = useRef(true)

  // Al cambiar de página, el foco va al contenido (los lectores de pantalla anuncian la página nueva).
  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    main.current?.focus({ preventScroll: true })
    window.scrollTo({ top: 0 })
  }, [loc.pathname])

  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#contenido"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[60] focus:rounded-lg focus:bg-accent focus:px-3 focus:py-2 focus:text-accent-fg"
      >
        Saltar al contenido
      </a>
      <header className="sticky top-0 z-40 border-b border-line bg-bg/80 backdrop-blur-xl">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-4">
          <MobileNav />
          <Link to="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <span className="grid size-8 place-items-center rounded-xl bg-accent text-accent-fg shadow-sm">
              <Plane className="size-4 -rotate-45" aria-hidden="true" />
            </span>
            <span className="hidden sm:inline">Flight Watcher</span>
          </Link>
          <DesktopNav />
          <div className="ml-auto flex items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => run.mutate(undefined)}
              disabled={status?.running}
              loading={run.isPending}
              title="Comprobar ahora todas tus vigilancias"
            >
              {!run.isPending && <Play />}
              <span className="hidden sm:inline">Comprobar todo</span>
              <span className="sr-only sm:hidden">Comprobar todo</span>
            </Button>
            <UserMenu />
          </div>
        </div>
        <RunningBanner />
      </header>

      <main ref={main} id="contenido" tabIndex={-1} className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 outline-none sm:py-8">
        <motion.div key={loc.pathname} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.22, ease: 'easeOut' }}>
          <Outlet />
        </motion.div>
      </main>

      <footer className="mx-auto w-full max-w-6xl px-4 py-6 text-xs text-muted">
        Próxima comprobación automática: {fmtDateTime(status?.next_run)} · Flight Watcher {meta ? `v${meta.version}` : ''}
      </footer>
      <Toaster
        theme={theme}
        position="bottom-right"
        closeButton
        toastOptions={{ className: 'font-sans' }}
      />
    </div>
  )
}
