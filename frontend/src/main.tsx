import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MotionConfig } from 'motion/react'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router'
import { ApiError, setUnauthorizedHandler } from './api/client'
import { keys } from './api/queries'
import './index.css'
import { ThemeProvider } from './lib/theme-context'
import { router } from './routes/router'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      // Los 4xx (sin permiso, no existe) no mejoran por reintentar.
      retry: (n, e) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2,
    },
  },
})

// Sesión caducada o cerrada desde otro sitio: se olvida el usuario y las rutas protegidas llevan al login.
setUnauthorizedHandler(() => queryClient.setQueryData(keys.me, null))

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <MotionConfig reducedMotion="user">
          <RouterProvider router={router} />
        </MotionConfig>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
)
