import AxeBuilder from '@axe-core/playwright'
import { expect, type Page } from '@playwright/test'

export const ADMIN = { user: 'admin', password: 'clave-de-prueba-1' }

export async function login(page: Page, user = ADMIN.user, password = ADMIN.password) {
  await page.goto('/login')
  await page.getByLabel('Usuario').fill(user)
  await page.getByLabel('Contraseña').fill(password)
  await page.getByRole('button', { name: 'Entrar' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Panel' })).toBeVisible()
}

/** Sin infracciones de accesibilidad graves (WCAG 2.1 AA) en la página tal como está. */
export async function expectAccessible(page: Page) {
  // Con las animaciones de entrada a medias, axe mediría colores aún semitransparentes.
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== 'running'))
  await page.waitForTimeout(400)
  const { violations } = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  const serious = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  expect(serious.map((v) => `${v.id}: ${v.help} → ${v.nodes.map((n) => n.target.join(' ')).slice(0, 3).join(' | ')}`)).toEqual([])
}
