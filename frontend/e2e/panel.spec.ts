import { expect, test } from '@playwright/test'
import { ADMIN, expectAccessible, login } from './helpers'

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
    // La URL de antes de la 2.0 (la de los avisos ya enviados) lleva al tramo dentro de su viaje.
    await expect(page).toHaveURL(/\/trips\/1\/legs\/1$/)
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

  test('el panel resume los viajes, los chollos de ahora y los avisos', async ({ page }) => {
    await expect(page.getByRole('region', { name: 'Viajes' })).toContainText(/de ida y vuelta/)
    await expect(page.getByRole('region', { name: 'El más barato ahora' }).getByRole('link', { name: 'Sevilla ⇄ Tenerife' }))
      .toHaveAttribute('href', '/trips/1')
    // El viaje sembrado avisa por debajo de 80 € y los precios simulados bajan de eso: sale como chollo.
    await expect(page.locator('section', { has: page.getByRole('heading', { name: 'Chollos ahora' }) })
      .getByRole('link', { name: 'Sevilla ⇄ Tenerife' })).toHaveAttribute('href', '/trips/1')
    await expect(page.getByRole('region', { name: 'Últimas ejecuciones' }).getByRole('link', { name: 'Sevilla → Tenerife' }).first())
      .toHaveAttribute('href', '/trips/1/legs/1')
    await expect(page.getByText('Próximamente:')).toBeVisible()
    // Ya no hay apartado de vuelos: todo cuelga de los viajes.
    const nav = page.getByRole('navigation', { name: 'Principal' })
    await expect(nav.getByRole('link', { name: 'Vuelos' })).toHaveCount(0)
    await expectAccessible(page)
    await nav.getByRole('link', { name: 'Viajes' }).click()
    await expect(page).toHaveURL(/\/trips$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Viajes' })).toBeVisible()
  })

  test('las URL del apartado de vuelos llevan a los viajes', async ({ page }) => {
    await page.goto('/flights')
    await expect(page).toHaveURL(/\/trips$/)
    await page.goto('/flights/2')
    await expect(page).toHaveURL(/\/trips\/1\/legs\/2$/)
    await page.goto('/watches/1/edit')
    await expect(page).toHaveURL(/\/trips\/1\/edit$/)
    await page.goto('/trips/99/legs/1') // un tramo con otro viaje en la URL lleva a la de su viaje
    await expect(page).toHaveURL(/\/trips\/1\/legs\/1$/)
    await page.goto('/flights/9999')
    await expect(page.getByText('No existe ese tramo de viaje')).toBeVisible()
  })

  test('detalle de un tramo: calendario, filtro por web, historial de un día y gráficas', async ({ page }) => {
    await page.goto('/trips/1')
    await page.getByRole('link', { name: 'Sevilla → Tenerife' }).first().click()
    await expect(page).toHaveURL(/\/trips\/1\/legs\/1$/)
    await expect(page.getByRole('link', { name: 'Sevilla ⇄ Tenerife' }).first()).toBeVisible()
    await expect(page.getByText(/Tramo de ida del viaje/)).toBeVisible()
    await expect(page.getByRole('link', { name: 'Editar el viaje' })).toHaveAttribute('href', '/trips/1/edit')
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

  test('comprobar ahora muestra el progreso y refresca al terminar', async ({ page }) => {
    await page.getByRole('button', { name: 'Comprobar todo' }).click()
    await expect(page.getByText('Comprobación terminada').first()).toBeVisible({ timeout: 20_000 })
    await expect(page.getByRole('button', { name: 'Comprobar todo' })).toBeEnabled()
  })
})

test.describe('viajes', () => {
  test.beforeEach(async ({ page }) => login(page))

  test('lista y detalle de un viaje: el total más barato con un enlace por tramo, en claro y oscuro', async ({ page }) => {
    await page.getByRole('navigation', { name: 'Principal' }).getByRole('link', { name: 'Viajes' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Viajes' })).toBeVisible()
    const card = page.getByRole('region', { name: 'Sevilla ⇄ Tenerife' })
    await expect(card.getByText('Viaje más barato ahora')).toBeVisible()
    await expect(card.getByRole('link', { name: /^Vueling \d+ €/ }).first()).toHaveAttribute('href', /tickets\.vueling\.com/)
    await expect(card.getByText('Avisa a: Discord de casa')).toBeVisible()
    await expectAccessible(page)

    await page.getByRole('button', { name: /Menú de/ }).click()
    await page.getByRole('menuitemradio', { name: 'Oscuro' }).click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    await page.keyboard.press('Escape')
    await expectAccessible(page)
    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    await page.getByRole('button', { name: /Menú de/ }).click()
    await page.getByRole('menuitemradio', { name: 'Como el sistema' }).click()
    await page.keyboard.press('Escape')

    await card.getByRole('link', { name: 'Sevilla ⇄ Tenerife' }).click()
    await expect(page).toHaveURL(/\/trips\/1$/)
    const combos = page.getByRole('region', { name: 'Combinaciones más baratas' })
    await expect(combos.locator('tbody tr').nth(5)).toBeVisible()
    const nights = page.getByRole('region', { name: 'Todas las noches de una fecha de ida' })
    await expect(nights.locator('tbody tr').first()).toBeVisible()
    await nights.getByLabel('Fecha de ida').selectOption({ index: 4 })
    await expect(nights.locator('tbody tr').first()).toBeVisible()
    await expect(page.getByRole('region', { name: 'Total por fecha de ida' }).locator('figure svg').first()).toBeVisible()
    await expectAccessible(page)
  })

  test('crear, validar, editar y eliminar un viaje con sus tramos', async ({ page }) => {
    await page.goto('/trips')
    await page.getByRole('link', { name: 'Nuevo viaje' }).click()
    await expect(page).toHaveURL(/\/trips\/new$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Nuevo viaje' })).toBeVisible()
    await expectAccessible(page)
    await page.getByRole('button', { name: 'Crear viaje' }).click()
    await expect(page.getByRole('alert')).toContainText('aeropuerto, ciudad, país o grupo')

    const name = `Escapada ${Date.now() % 100000}` // el servidor puede reutilizarse entre ejecuciones
    await page.getByLabel('Nombre (opcional)').fill(name)
    // Autocompletado accesible: se escribe, se baja con las flechas y se elige con Intro.
    const origin = page.getByRole('combobox', { name: 'Origen de la ida' })
    await origin.fill('malaga')
    await expect(page.getByRole('option', { name: /Málaga \(AGP\)/ })).toBeVisible()
    await expectAccessible(page)
    await origin.press('Enter')
    await expect(origin).toHaveValue('Málaga (AGP)')
    await page.getByRole('combobox', { name: 'Destino de la ida' }).fill('barcelona')
    await page.getByRole('option', { name: /Barcelona \(BCN\)/ }).click()

    // Comprobación de la ruta: las webs que no la operan no se pueden marcar y dicen por qué.
    const outWebs = page.getByRole('group', { name: 'Webs de la ida' })
    await expect(outWebs.getByText('Vueling no opera esta ruta.')).toBeVisible()
    await expect(outWebs.getByRole('checkbox', { name: 'Vueling' })).toBeDisabled()
    await expect(outWebs.getByRole('checkbox', { name: 'MockWeb' })).toBeChecked()
    await outWebs.getByRole('checkbox', { name: 'Buscador' }).click()
    await page.getByLabel('Escalas de la ida').selectOption({ label: 'Hasta 1 escala' })

    // La vuelta, al revés que la ida.
    await page.getByRole('button', { name: 'Al revés que la ida' }).click()
    await expect(page.getByRole('combobox', { name: 'Origen de la vuelta' })).toHaveValue('Barcelona (BCN)')
    await expect(page.getByRole('combobox', { name: 'Destino de la vuelta' })).toHaveValue('Málaga (AGP)')
    await expect(page.getByRole('group', { name: 'Webs de la vuelta' }).getByRole('checkbox', { name: 'MockWeb' })).toBeChecked()

    await page.getByLabel('Noches como mínimo').fill('6')
    await page.getByLabel('Noches como máximo').fill('2')
    await expectAccessible(page)
    await page.getByRole('button', { name: 'Crear viaje' }).click()
    await expect(page.getByRole('alert')).toContainText('no pueden ser más que las máximas')
    await page.getByLabel('Noches como máximo').fill('8')
    await page.getByLabel('Si el total cuesta como mucho (€)').fill('150')
    await page.getByRole('button', { name: 'Crear viaje' }).click()

    await expect(page.getByRole('heading', { level: 1 })).toContainText(name)
    await expect(page.getByText('Viaje creado').first()).toBeVisible()
    await expect(page.getByText(/6–8 noches · avisa si el total ≤ 150 €/)).toBeVisible()
    await page.getByRole('link', { name: 'AGP → BCN' }).click()
    await expect(page.getByText(/Tramo de ida del viaje .*hasta 1 escala/)).toBeVisible()
    await page.getByRole('link', { name }).first().click()

    // Pasa a solo ida: la vuelta (con su histórico) se borra.
    await page.getByRole('link', { name: 'Editar' }).click()
    await page.getByRole('checkbox', { name: 'Solo ida (sin vuelta)' }).click()
    await expect(page.getByRole('combobox', { name: 'Origen de la vuelta' })).toHaveCount(0)
    await page.getByRole('button', { name: 'Guardar cambios' }).click()
    await expect(page.getByText(/solo ida · avisa si el precio ≤ 150 €/)).toBeVisible()
    await expect(page.getByText(/Vuelta:/)).toHaveCount(0)

    await page.getByRole('link', { name: 'Editar' }).click()
    await page.getByRole('button', { name: 'Eliminar' }).click()
    await expect(page.getByRole('alertdialog')).toBeVisible()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Eliminar' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Viajes' })).toBeVisible()
    await expect(page.getByRole('link', { name })).toHaveCount(0)
  })

  test('un viaje de solo alojamiento con viajeros y filtros', async ({ page }) => {
    const name = `Escapada isla ${Date.now() % 100000}`
    await page.goto('/trips/new')
    await page.getByLabel('Nombre (opcional)').fill(name)
    const what = page.getByRole('group', { name: 'Qué vigila el viaje' })
    await what.getByRole('checkbox', { name: 'Transporte' }).click()
    await expect(page.getByRole('combobox', { name: 'Origen de la ida' })).toHaveCount(0)
    await expect(page.getByText('Marca el transporte, el alojamiento o los dos.')).toBeVisible()
    await what.getByRole('checkbox', { name: 'Alojamiento' }).click()

    // Viajeros: dos adultos (uno, residente en Canarias) y una niña de 8 años.
    await page.getByRole('button', { name: 'Añadir viajero' }).click()
    await page.getByRole('button', { name: 'Añadir viajero' }).click()
    await page.getByLabel('Viajero 1: residencia').selectOption({ label: 'Residente en Canarias' })
    await page.getByLabel('Viajero 3: edad').selectOption({ label: '8 años' })

    await page.getByLabel('Destino del alojamiento').fill('Puerto de la Cruz')
    await expect(page.getByRole('group', { name: 'Webs del alojamiento' }).getByRole('checkbox', { name: 'Casas de prueba' })).toBeChecked()
    const types = page.getByRole('group', { name: 'Tipos de alojamiento' })
    await types.getByRole('checkbox', { name: 'Hotel', exact: true }).click()
    await types.getByRole('checkbox', { name: 'Apartamento' }).click()
    await page.getByLabel('Puntuación mínima').selectOption({ label: '8 o más (sobre 10)' })
    await page.getByLabel('Noches como mínimo').fill('2')
    await page.getByLabel('Noches como máximo').fill('3')
    const today = new Date()
    const iso = (days: number) => new Date(today.getTime() + days * 86_400_000).toISOString().slice(0, 10)
    await page.getByLabel('Entrada desde (opcional)').fill(iso(5))
    await page.getByLabel('Entrada hasta (opcional)').fill(iso(7))
    await page.getByLabel('…o si sale como mucho por persona (€)').fill('70')
    await expectAccessible(page)
    await page.getByRole('button', { name: 'Crear viaje' }).click()

    await expect(page.getByRole('heading', { level: 1 })).toContainText(name)
    await expect(page.getByText(/2–3 noches · 2 adultos y 1 niño \(8 años\) · 1 residente en Canarias/)).toBeVisible()
    await expect(page.getByText('Estancia más barata ahora')).toBeVisible()
    await page.getByRole('button', { name: 'Comprobar ahora' }).click()
    await expect(page.getByText('Comprobación terminada').first()).toBeVisible({ timeout: 20_000 })
    const combos = page.getByRole('region', { name: 'Combinaciones más baratas' })
    // Pasa los filtros el hotel (el hostal no es de los tipos elegidos y el apartamento tiene un 7,5).
    await expect(combos.getByRole('link', { name: /Casas de prueba \d+ €/ }).first()).toHaveAttribute('href', 'https://casas.test/hotel-playa')
    await expect(combos.getByText(/Hotel Playa · hotel, 4★, nota 8,6/).first()).toBeVisible()
    await expect(combos.getByText(/€\/persona/).first()).toBeVisible()
    await expect(page.getByRole('region', { name: 'Todas las noches de una fecha de entrada' })).toBeVisible()
    await expectAccessible(page)

    await page.getByRole('link', { name: 'Alojamiento en Puerto de la Cruz' }).click()
    await expect(page.getByText(/Alojamiento del viaje .*hotel o apartamento · nota 8\+/)).toBeVisible()
    await expect(page.getByRole('region', { name: 'Estancias más baratas' }).locator('tbody tr').first()).toBeVisible()
    await expect(page.getByRole('region', { name: 'Precios por fecha de entrada' }).locator('table').first()).toBeVisible()
    await expectAccessible(page)

    await page.getByRole('link', { name: 'Editar el viaje' }).click()
    await expect(page.getByLabel('Destino del alojamiento')).toHaveValue('Puerto de la Cruz')
    await expect(page.getByLabel('Viajero 3: edad')).toHaveValue('8')
    await page.getByRole('button', { name: 'Eliminar' }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Eliminar' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Viajes' })).toBeVisible()
  })

  test('las URL antiguas de «nueva vigilancia» precargan un viaje nuevo', async ({ page }) => {
    const name = `Budapest ${Date.now() % 100000}`
    await page.goto('/watches/new?origin=BCN&destination=BUD')
    await expect(page).toHaveURL(/\/trips\/new\?origin=BCN&destination=BUD$/)
    await expect(page.getByRole('combobox', { name: 'Origen de la ida' })).toHaveValue('Barcelona (BCN)')
    await expect(page.getByRole('combobox', { name: 'Destino de la ida' })).toHaveValue('Budapest (BUD)')
    await expect(page.getByRole('combobox', { name: 'Origen de la vuelta' })).toHaveValue('Budapest (BUD)')
    await expect(page.getByRole('group', { name: 'Webs de la ida' }).getByRole('checkbox', { name: 'Wizz Air' })).toBeChecked()
    await page.getByLabel('Nombre (opcional)').fill(name)
    await page.getByRole('checkbox', { name: 'Solo ida (sin vuelta)' }).click()
    await expect(page.getByLabel('Noches como mínimo')).toHaveCount(0)
    await expectAccessible(page)
    await page.getByRole('button', { name: 'Crear viaje' }).click()
    await expect(page.getByRole('heading', { level: 1 })).toContainText(name)
    await expect(page.getByLabel('solo ida').first()).toBeVisible()
    await expect(page.getByRole('region', { name: 'Fechas más baratas' })).toBeVisible()
    await expectAccessible(page)

    await page.getByRole('link', { name: 'Editar' }).click()
    await page.getByRole('button', { name: 'Eliminar' }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Eliminar' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Viajes' })).toBeVisible()
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

test.describe('proveedores', () => {
  test.beforeEach(async ({ page }) => login(page))

  test('probar el acceso a los proveedores', async ({ page }) => {
    await page.getByRole('link', { name: 'Proveedores' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Proveedores' })).toBeVisible()
    await expectAccessible(page)

    const vueling = page.getByRole('region', { name: 'Vueling' })
    await vueling.getByRole('button', { name: 'Probar Vueling' }).click()
    await expect(vueling.getByText('Accesible', { exact: true })).toBeVisible({ timeout: 20_000 })
    await expect(vueling.getByText(/Responde: opera SVQ→TFN/)).toBeVisible()

    await page.getByLabel('Origen de la prueba (opcional)').fill('mad')
    await page.getByRole('button', { name: 'Probar todos' }).click()
    await expect(page.getByRole('alert')).toContainText('Indica origen y destino')
    await page.getByLabel('Destino de la prueba (opcional)').fill('bcn')
    await page.getByRole('button', { name: 'Probar todos' }).click()
    await expect(page.getByRole('region', { name: 'Cambio de divisas (BCE)' }).getByText('Accesible', { exact: true }))
      .toBeVisible({ timeout: 30_000 })
    await expectAccessible(page)
  })

  test('crear, probar con la consola, exportar y eliminar un proveedor', async ({ page }) => {
    const key = `e2e${Date.now() % 100_000}`
    const name = `Aerolínea ${key}`
    await page.goto('/admin/providers')
    await page.getByRole('link', { name: 'Nuevo proveedor' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Nuevo proveedor' })).toBeVisible()
    await expect(page.getByLabel('Código', { exact: true })).toHaveValue(/def fetch_route/)
    await expectAccessible(page)

    await page.getByLabel('Clave', { exact: true }).fill(key)
    await page.getByLabel('Nombre', { exact: true }).fill(name)
    await page.getByLabel('Cobertura', { exact: true }).selectOption('universal')
    await page.getByLabel('Ruta de prueba: origen').fill('svq')
    await page.getByLabel('Ruta de prueba: destino').fill('bcn')
    await page.getByLabel('Código', { exact: true }).fill([
      'def fetch_route(api, origin, destination, start, max_months):',
      '    api.log("ruta", origin, destination)',
      '    return {start + timedelta(days=d): 40 + d for d in range(5, 9)}',
    ].join('\n'))

    const testBox = page.getByRole('region', { name: 'Probar sin guardar' })
    await testBox.getByRole('button', { name: 'Probar el script' }).click()
    await expect(testBox.getByRole('alert')).toContainText('Confirma tu contraseña')
    await page.getByLabel('Tu contraseña').fill(ADMIN.password)
    await testBox.getByRole('button', { name: 'Probar el script' }).click()
    const log = testBox.getByRole('log', { name: 'Salida de la prueba' })
    await expect(log).toContainText('Mensaje del script: ruta SVQ BCN', { timeout: 20_000 })
    await expect(log).toContainText('4 días con precio para SVQ→BCN; el más barato, 45 EUR')
    await expect(testBox.getByText('Accesible', { exact: true })).toBeVisible()
    await expect(testBox.getByRole('table')).toContainText('SVQ→BCN')
    await expectAccessible(page)

    await page.getByRole('button', { name: 'Crear proveedor' }).click()
    await expect(page.getByRole('heading', { level: 1, name: `Editar ${name}` })).toBeVisible()
    await page.getByRole('link', { name: 'Proveedores', exact: true }).first().click()
    const card = page.getByRole('region', { name, exact: true })
    await expect(card).toContainText(key)

    await card.getByRole('checkbox', { name: `Elegir ${name} para exportar` }).click()
    const download = page.waitForEvent('download')
    await page.getByRole('link', { name: 'Exportar los elegidos (1)' }).click()
    expect((await download).suggestedFilename()).toBe(`proveedores-${key}.fwp`)

    await card.getByRole('link', { name: `Editar ${name}` }).click()
    await page.getByRole('button', { name: 'Eliminar' }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Eliminar' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Proveedores' })).toBeVisible()
    await expect(page.getByRole('region', { name, exact: true })).toHaveCount(0)
  })

  test('importar proveedores desde un enlace, revisando su código', async ({ page }) => {
    await page.goto('/admin/providers')
    await page.getByRole('link', { name: 'Importar' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Importar proveedores' })).toBeVisible()
    await expectAccessible(page)

    await page.getByRole('button', { name: 'Catálogo de Trip Watch' }).click()
    const found = page.getByRole('region', { name: /Qué trae/ })
    await expect(found.getByRole('checkbox', { name: /Wizz Air/ })).toBeVisible()
    // Del catálogo son nuevos Air Europa, Iberia Express y Binter (los demás ya están): vienen marcados y aquí no se quieren.
    for (const name of [/Air Europa/, /Iberia Express/, /Binter/]) {
      await expect(found.getByRole('checkbox', { name })).toBeChecked()
      await found.getByRole('checkbox', { name }).click()
    }
    await expect(found.getByText('Igual que el guardado').first()).toBeVisible()
    await found.getByText('Ver el código').first().click()
    await expect(found.getByLabel('Código de Wizz Air')).toContainText('def fetch_route(api, origin, destination, start, max_months):')
    await expectAccessible(page)

    await found.getByRole('checkbox', { name: /Wizz Air/ }).click()
    await page.getByRole('button', { name: 'Importar 1 proveedor' }).click()
    await expect(page.getByRole('alert')).toContainText('Confirma tu contraseña')
    await page.getByLabel('Tu contraseña').fill(ADMIN.password)
    await page.getByRole('button', { name: 'Importar 1 proveedor' }).click()
    await expect(page.getByText('1 proveedor importado')).toBeVisible()
    await expect(page.getByRole('heading', { level: 1, name: 'Proveedores' })).toBeVisible()
  })
})

test('en el móvil el menú lleva a todas las secciones y nada se sale de la pantalla @movil', async ({ page, isMobile }) => {
  test.skip(!isMobile, 'solo en móvil')
  await login(page)
  for (const path of ['/', '/trips', '/trips/1', '/trips/1/legs/1', '/trips/new', '/trips/1/edit', '/profile', '/admin/users', '/admin/providers', '/admin/providers/new', '/admin/providers/import', '/settings', '/runs']) {
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
