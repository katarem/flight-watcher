import { createBrowserRouter } from 'react-router'
import { AppShell } from '@/components/layout/AppShell'
import { ChannelFormPage } from '@/pages/ChannelFormPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { LoginPage } from '@/pages/LoginPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { ProfilePage } from '@/pages/ProfilePage'
import { TripFormPage } from '@/pages/TripFormPage'
import { TripsPage } from '@/pages/TripsPage'
import { RequireAdmin, RequireAuth } from './guards'
import { LegacyWatch } from './legacy'

/** Páginas que se cargan al visitarlas (las gráficas y la administración no hacen falta al entrar). */
const page = (load: () => Promise<Record<string, React.ComponentType>>, name: string, adminOnly = false) => ({
  lazy: async () => {
    const Page = (await load())[name]
    return { Component: adminOnly ? () => <RequireAdmin><Page /></RequireAdmin> : Page }
  },
})

const admin = (el: React.ReactNode) => <RequireAdmin>{el}</RequireAdmin>

// Todo vive en los viajes: cada tramo (una vigilancia interna) tiene su detalle dentro de su viaje. Las URL de antes de
// la 2.0 (/watches/…, que sale en los avisos ya enviados, y /flights/… de la 1.9) llevan a su viaje o a su tramo.
const legacy = ['watches', 'flights'].flatMap((base) =>
  ['', '/new', '/:id', '/:id/edit'].map((rest) => ({ path: `${base}${rest}`, element: <LegacyWatch /> })))

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
      { path: 'trips', element: <TripsPage /> },
      { path: 'trips/new', element: <TripFormPage /> },
      { path: 'trips/:id', ...page(() => import('@/pages/TripDetailPage'), 'TripDetailPage') },
      { path: 'trips/:id/edit', element: <TripFormPage /> },
      { path: 'trips/:id/legs/:legId', ...page(() => import('@/pages/LegDetailPage'), 'LegDetailPage') },
      ...legacy,
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
      { path: 'admin/providers/new', ...page(() => import('@/pages/ProviderFormPage'), 'ProviderFormPage', true) },
      { path: 'admin/providers/import', ...page(() => import('@/pages/ProviderImportPage'), 'ProviderImportPage', true) },
      { path: 'admin/providers/:key/edit', ...page(() => import('@/pages/ProviderFormPage'), 'ProviderFormPage', true) },
      { path: 'settings', ...page(() => import('@/pages/SettingsPage'), 'SettingsPage', true) },
      { path: 'debug', ...page(() => import('@/pages/DebugPage'), 'DebugPage', true) },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
