import { createBrowserRouter, Navigate } from 'react-router'
import { AppShell } from '@/components/layout/AppShell'
import { ChannelFormPage } from '@/pages/ChannelFormPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { LoginPage } from '@/pages/LoginPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { ProfilePage } from '@/pages/ProfilePage'
import { WatchFormPage } from '@/pages/WatchFormPage'
import { RequireAdmin, RequireAuth } from './guards'

/** Páginas que se cargan al visitarlas (las gráficas y la administración no hacen falta al entrar). */
const page = (load: () => Promise<Record<string, React.ComponentType>>, name: string, adminOnly = false) => ({
  lazy: async () => {
    const Page = (await load())[name]
    return { Component: adminOnly ? () => <RequireAdmin><Page /></RequireAdmin> : Page }
  },
})

const admin = (el: React.ReactNode) => <RequireAdmin>{el}</RequireAdmin>

// Mismas URL que el panel anterior: los enlaces de los avisos (/watches/{id}) siguen funcionando.
export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    // Mientras llega una página que se carga aparte (solo en la primera visita).
    hydrateFallbackElement: <div className="min-h-dvh" />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'watches', element: <Navigate to="/" replace /> },
      { path: 'watches/new', element: <WatchFormPage /> },
      { path: 'watches/:id', ...page(() => import('@/pages/WatchDetailPage'), 'WatchDetailPage') },
      { path: 'watches/:id/edit', element: <WatchFormPage /> },
      { path: 'runs', ...page(() => import('@/pages/RunsPage'), 'RunsPage') },
      { path: 'profile', element: <ProfilePage /> },
      { path: 'profile/channels/new', element: <ChannelFormPage /> },
      { path: 'profile/channels/:cid/edit', element: <ChannelFormPage /> },
      { path: 'admin/users', ...page(() => import('@/pages/UsersPage'), 'UsersPage', true) },
      { path: 'admin/users/new', ...page(() => import('@/pages/UserFormPage'), 'UserFormPage', true) },
      { path: 'admin/users/:uid/edit', ...page(() => import('@/pages/UserFormPage'), 'UserFormPage', true) },
      { path: 'admin/users/:uid/channels/new', element: admin(<ChannelFormPage />) },
      { path: 'admin/users/:uid/channels/:cid/edit', element: admin(<ChannelFormPage />) },
      { path: 'admin/providers', ...page(() => import('@/pages/ProvidersPage'), 'ProvidersPage', true) },
      { path: 'settings', ...page(() => import('@/pages/SettingsPage'), 'SettingsPage', true) },
      { path: 'debug', ...page(() => import('@/pages/DebugPage'), 'DebugPage', true) },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
