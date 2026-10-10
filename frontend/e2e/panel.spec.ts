import { expect, test } from '@playwright/test'
import { expectAccessible, login } from './helpers'

test.describe('sesión', () => {
  test('sin sesión lleva al login recordando a dónde ibas @movil', async ({ page }) => {
    await page.goto('/watches/1')
    await expect(page).toHaveURL(/\/login\?next=%2Fwatches%2F1$/)
    await expectAccessible(page)
    await page.getByLabel('Usuario').fill('admin')
    await page.getByLabel('Contraseña').fill('mala')
    await page.getByRole('button', { name: 'Entrar' }).click()
    await expect(page.getByRole('alert')).toContainText('Usuario o contraseña incorrectos')
    await page.getByLabel('Contraseña').fill('clave-de-prueba-1')
    await page.getByRole('button', { name: 'Entrar' }).click()
    await expect(page).toHaveURL(/\/watches\/1$/)
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Sevilla → Tenerife')
  })

  test('cerrar sesión', async ({ page }) => {
    await login(page)
    await page.getByRole('button', { name: /Menú de/ }).click()
    await page.getByRole('menuitem', { name: 'Cerrar sesión' }).click()
    await expect(page).toHaveURL(/\/login/)
    await page.goto('/')
    await expect(page).toHaveURL(/\/login/)
  })
})

test.describe('panel', () => {
  test.beforeEach(async ({ page }) => login(page))

  test('vigilancias con el mejor precio por web y accesible en claro y oscuro', async ({ page }) => {
    const card = page.getByRole('region', { name: 'Sevilla → Tenerife' })
    await expect(card.getByText('Vueling', { exact: true })).toBeVisible()
    await expect(card.getByText('Ryanair', { exact: true })).toBeVisible()
    await expect(card.getByRole('link', { name: /Ver esa fecha en Vueling/ })).toHaveAttribute('href', /tickets\.vueling\.com.*d=TFN/)
    await expect(card.getByText('Avisa a: Discord de casa')).toBeVisible()
    await expectAccessible(page)

    await page.getByRole('button', { name: /Menú de/ }).click()
    await page.getByRole('menuitemradio', { name: 'Oscuro' }).click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    await page.keyboard.press('Escape')
    await expectAccessible(page)
    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  })

  test('detalle: calendario, filtro por web, historial de un día y gráficas', async ({ page }) => {
    await page.getByRole('link', { name: 'Sevilla → Tenerife' }).first().click()
    await expect(page).toHaveURL(/\/watches\/1$/)
    const calendar = page.getByRole('region', { name: 'Precios por fecha de vuelo' })
    await expect(calendar.locator('table').first()).toBeVisible()
    const priceLinks = calendar.getByRole('link', { name: /Ryanair:/ })
    expect(await priceLinks.count()).toBeGreaterThan(5)

    await calendar.getByRole('button', { name: 'Vueling', exact: true }).click()
    await expect(calendar.getByRole('link', { name: /Ryanair:/ })).toHaveCount(0)
    await calendar.getByRole('button', { name: 'Todas' }).click()

    const day = calendar.getByRole('button', { name: /Ver historial de esta fecha/ }).nth(3)
    await day.click()
    await expect(day).toHaveAttribute('aria-pressed', 'true')
    const history = page.getByRole('region', { name: 'Historial de una fecha concreta' })
    await expect(history.locator('figure svg').first()).toBeVisible()
    await expect(page.getByRole('region', { name: 'Evolución del precio mínimo' }).locator('figure svg').first()).toBeVisible()
    await expectAccessible(page)
  })

  test('crear, validar, editar y eliminar una vigilancia', async ({ page }) => {
    await page.getByRole('link', { name: 'Nueva vigilancia' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Nueva vigilancia' })).toBeVisible()
    await expectAccessible(page)

    await page.getByLabel('Origen (IATA)').fill('ag')
    await page.getByRole('button', { name: 'Crear vigilancia' }).click()
    await expect(page.getByRole('alert')).toContainText('código IATA')

    await page.getByLabel('Nombre (opcional)').fill('Málaga → Barcelona')
    await page.getByLabel('Origen (IATA)').fill('agp')
    await page.getByLabel('Destino (IATA)').fill('bcn')
    await expect(page.getByLabel('Origen (IATA)')).toHaveValue('AGP')
    await page.getByRole('checkbox', { name: 'Ryanair' }).click()
    await page.getByLabel('Si cuesta como mucho (€)').fill('35')
    await page.getByRole('button', { name: 'Crear vigilancia' }).click()

    await expect(page.getByRole('heading', { level: 1 })).toContainText('Málaga → Barcelona')
    await expect(page.getByText('Vigilancia creada').first()).toBeVisible()
    await expect(page.getByText(/avisa si ≤ 35 €/)).toBeVisible()

    await page.getByRole('link', { name: 'Editar' }).click()
    await page.getByRole('button', { name: 'Intercambiar origen y destino' }).click()
    await page.getByRole('button', { name: 'Guardar cambios' }).click()
    await expect(page.getByText('BCN', { exact: false }).first()).toBeVisible()

    await page.getByRole('link', { name: 'Editar' }).click()
    await page.getByRole('button', { name: 'Eliminar' }).click()
    await expect(page.getByRole('alertdialog')).toBeVisible()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Eliminar' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Panel' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Málaga → Barcelona' })).toHaveCount(0)
  })

  test('comprobar ahora muestra el progreso y refresca al terminar', async ({ page }) => {
    await page.getByRole('button', { name: 'Comprobar todo' }).click()
    await expect(page.getByText('Comprobación terminada').first()).toBeVisible({ timeout: 20_000 })
    await expect(page.getByRole('button', { name: 'Comprobar todo' })).toBeEnabled()
  })
})

test.describe('perfil y canales', () => {
  test.beforeEach(async ({ page }) => login(page))

  test('añadir, probar y eliminar un canal sin ver nunca el secreto', async ({ page }) => {
    await page.goto('/profile')
    await expectAccessible(page)
    await page.getByRole('link', { name: 'Añadir canal' }).click()
    await page.getByRole('link', { name: /Discord/ }).click()
    await page.getByLabel('Nombre').fill('Discord del trabajo')
    await page.getByLabel('Webhook de Discord').fill('https://evil.example/hook')
    await page.getByRole('button', { name: 'Añadir canal' }).click()
    await expect(page.getByRole('alert')).toContainText('webhook de Discord no es válida')
    await page.getByLabel('Webhook de Discord').fill('https://discord.com/api/webhooks/9/secreto-e2e')
    await page.getByRole('button', { name: 'Añadir canal' }).click()

    await expect(page).toHaveURL(/\/profile$/)
    const row = page.getByRole('listitem').filter({ hasText: 'Discord del trabajo' })
    await row.getByRole('button', { name: 'Probar' }).click()
    await expect(page.getByText('Mensaje de prueba enviado').first()).toBeVisible()
    await row.getByRole('link', { name: 'Editar' }).click()
    await expect(page.getByLabel('Webhook de Discord')).toHaveValue('')
    await expect(page.getByText('Hay uno guardado')).toBeVisible()
    expect(await page.content()).not.toContain('secreto-e2e')
    await page.getByRole('link', { name: 'Cancelar' }).click()

    await row.getByRole('button', { name: 'Eliminar' }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Eliminar' }).click()
    await expect(page.getByRole('listitem').filter({ hasText: 'Discord del trabajo' })).toHaveCount(0)
  })
})

test.describe('administración', () => {
  test.beforeEach(async ({ page }) => login(page))

  test('usuarios y ajustes', async ({ page }) => {
    await page.getByRole('link', { name: 'Usuarios' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Usuarios' })).toBeVisible()
    await expectAccessible(page)
    await page.getByRole('link', { name: 'Nuevo usuario' }).click()
    const name = `lucia${Date.now() % 100000}` // el servidor puede reutilizarse entre ejecuciones
    await page.getByLabel('Usuario', { exact: true }).fill(name)
    await page.getByLabel('Contraseña').fill('una-clave-segura')
    await page.getByRole('button', { name: 'Crear usuario' }).click()
    await expect(page.getByRole('heading', { level: 1, name: `Editar @${name}` })).toBeVisible()
    await expect(page.getByRole('heading', { name: `Canales de aviso de @${name}` })).toBeVisible()

    await page.getByRole('link', { name: 'Ajustes' }).click()
    await expectAccessible(page)
    await page.getByLabel('Horas (0-23, separadas por comas)').fill('99')
    await page.getByRole('button', { name: 'Guardar ajustes' }).click()
    await expect(page.getByRole('alert')).toContainText('Las horas deben ser')
    await page.getByLabel('Horas (0-23, separadas por comas)').fill('8,20')
    await page.getByRole('button', { name: 'Guardar ajustes' }).click()
    await expect(page.getByText('Ajustes guardados').first()).toBeVisible()
  })
})

test('en el móvil el menú lleva a todas las secciones y nada se sale de la pantalla @movil', async ({ page, isMobile }) => {
  test.skip(!isMobile, 'solo en móvil')
  await login(page)
  for (const path of ['/', '/watches/1', '/watches/new', '/profile', '/admin/users', '/settings', '/runs']) {
    await page.goto(path)
    await page.waitForLoadState('networkidle')
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow, `desbordamiento horizontal en ${path}`).toBeLessThanOrEqual(0)
  }
  await page.goto('/')
  await page.getByRole('button', { name: 'Abrir menú' }).click()
  await page.getByRole('dialog').getByRole('link', { name: 'Ejecuciones' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Ejecuciones' })).toBeVisible()
})
