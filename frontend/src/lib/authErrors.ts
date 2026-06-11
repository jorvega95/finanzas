// Traducción es-MX de errores de Supabase Auth (GoTrue responde en inglés;
// la localización es responsabilidad del cliente). Fallback: mensaje original.
const BY_CODE: Record<string, string> = {
  user_already_exists: "Este correo ya está registrado. Inicia sesión.",
  email_exists: "Este correo ya está registrado. Inicia sesión.",
  invalid_credentials: "Correo o contraseña incorrectos.",
  email_not_confirmed:
    "Tu correo aún no está confirmado. Revisa tu bandeja (y spam).",
  weak_password: "La contraseña es demasiado débil: usa al menos 8 caracteres.",
  over_request_rate_limit: "Demasiados intentos. Espera un minuto y reintenta.",
  over_email_send_rate_limit:
    "Se enviaron demasiados correos. Espera unos minutos.",
  same_password: "La nueva contraseña debe ser distinta a la actual.",
  validation_failed: "Revisa que el correo y la contraseña sean válidos.",
  signup_disabled: "El registro está deshabilitado por el momento.",
  provider_disabled: "Ese método de acceso no está habilitado.",
};

// Algunos errores viejos de GoTrue no traen `code`: se reconocen por texto.
const BY_MESSAGE: Array<[RegExp, string]> = [
  [/already registered/i, BY_CODE.user_already_exists],
  [/invalid login credentials/i, BY_CODE.invalid_credentials],
  [/email not confirmed/i, BY_CODE.email_not_confirmed],
  [/password should be at least/i, BY_CODE.weak_password],
  [/rate limit/i, BY_CODE.over_request_rate_limit],
  [/unable to validate email/i, "El correo no tiene un formato válido."],
];

export function translateAuthError(error: unknown): string {
  const code = (error as { code?: string } | null)?.code;
  if (code && BY_CODE[code]) return BY_CODE[code];
  const message = error instanceof Error ? error.message : "";
  for (const [pattern, translation] of BY_MESSAGE) {
    if (pattern.test(message)) return translation;
  }
  return message || "Ocurrió un error. Intenta de nuevo.";
}
