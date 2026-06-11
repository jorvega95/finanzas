// Espacio activo (GLO-05): el cliente HTTP manda X-Space-Id en cada request.
let activeSpaceId: string | null = null;

export function setActiveSpaceId(id: string | null) {
  activeSpaceId = id;
}

export function getActiveSpaceId(): string | null {
  return activeSpaceId;
}
