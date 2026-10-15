/** Rutas del panel que se enlazan desde varios sitios. Desde la 2.0 todo vive en los viajes: un tramo (vigilancia
 *  interna) tiene su página dentro de su viaje. */

/** Página de un viaje: «/trips/3», «/trips/3/edit». */
export const tripPath = (id: number | string, suffix = '') => `/trips/${id}${suffix}`

/** Detalle de un tramo dentro de su viaje: «/trips/3/legs/7». */
export const legPath = (tripId: number | string, legId: number | string) => `/trips/${tripId}/legs/${legId}`
