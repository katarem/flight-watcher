import { createContext, useContext, type ReactNode } from 'react'
import { useTheme, type ThemePref } from './theme'

const ThemeContext = createContext<[ThemePref, (p: ThemePref) => void]>(['system', () => {}])

export function ThemeProvider({ children }: { children: ReactNode }) {
  return <ThemeContext.Provider value={useTheme()}>{children}</ThemeContext.Provider>
}

export const useThemePref = () => useContext(ThemeContext)
