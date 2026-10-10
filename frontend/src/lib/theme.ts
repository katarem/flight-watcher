/** Tema claro/oscuro: «sistema» sigue la preferencia del sistema operativo. */
import { useEffect, useState } from 'react'

export type ThemePref = 'system' | 'light' | 'dark'
const KEY = 'fw-theme'
const media = () => window.matchMedia('(prefers-color-scheme: dark)')

function read(): ThemePref {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

function apply(pref: ThemePref) {
  const dark = pref === 'dark' || (pref === 'system' && media().matches)
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
}

export function useTheme(): [ThemePref, (p: ThemePref) => void] {
  const [pref, setPref] = useState<ThemePref>(read)
  useEffect(() => {
    apply(pref)
    if (pref !== 'system') return
    const m = media()
    const onChange = () => apply('system')
    m.addEventListener('change', onChange)
    return () => m.removeEventListener('change', onChange)
  }, [pref])
  const set = (p: ThemePref) => {
    try {
      localStorage.setItem(KEY, p)
    } catch {
      /* sin almacenamiento: el tema dura lo que la pestaña */
    }
    setPref(p)
  }
  return [pref, set]
}
