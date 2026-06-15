# Guía de inicio — Configurar Supabase y arrancar Finanzas

Esta guía te lleva de cero (nunca usaste Supabase) a tener la app corriendo
en tu máquina con login real y base de datos en la nube. Tiempo estimado:
**20-30 minutos**. Todo lo que usarás de Supabase entra en su **plan gratuito**.

> **¿Qué es Supabase y por qué lo usamos?**
> Supabase es un "backend en la nube" sobre PostgreSQL. La app lo usa para
> dos cosas exactamente: la **base de datos** Postgres y el **login** (Auth:
> Google y email/contraseña). Toda la lógica de negocio vive en tu FastAPI
> local — el frontend nunca lee datos directamente de Supabase.

---

## Paso 1 — Crear tu cuenta y proyecto

1. Entra a <https://supabase.com> y haz clic en **Start your project**.
   Puedes registrarte con tu cuenta de GitHub o con email.
2. Crea una organización si te la pide (nombre cualquiera, plan **Free**).
3. Clic en **New project** y llena:
   - **Name:** `finanzas` (o el que quieras).
   - **Database Password:** genera una y **GUÁRDALA en un lugar seguro**
     (la necesitarás en el Paso 3; Supabase no te la vuelve a mostrar).
     Evita caracteres como `@`, `:` o `/` para no tener que escaparla en la URL.
   - **Region:** la más cercana (p. ej. *East US* o *West US* desde México).
4. Clic en **Create new project** y espera 1-2 minutos a que aprovisione.

## Paso 2 — Recolectar las 4 credenciales

Todas están en el dashboard de tu proyecto. Ve apuntándolas:

| # | Credencial | Dónde está | La usa |
|---|---|---|---|
| 1 | **Project URL** | ⚙️ Project Settings → **API** → *Project URL* (`https://xxxx.supabase.co`) | frontend y backend |
| 2 | **anon / publishable key** | ⚙️ Project Settings → **API** → *Project API keys* → `anon` `public` (en proyectos nuevos puede llamarse *publishable key*, `sb_publishable_...`) | frontend |
| 3 | ~~JWT Secret~~ → **ya no se necesita** | Los proyectos nuevos usan *JWT Signing Keys* asimétricas (ver nota abajo) | — |
| 4 | **Cadena de conexión a la BD** | ⚙️ Project Settings → **Database** → *Connection string* (ver detalle abajo) | backend (SQLAlchemy/Alembic) |

### Nota sobre el JWT Secret (proyectos nuevos vs. legacy)

Supabase migró a **JWT Signing Keys asimétricas** (ES256/RS256): el dashboard
de un proyecto nuevo ya **no expone ningún "JWT Secret"**, y está bien —
nuestro backend lo soporta nativamente:

- **Proyecto nuevo (tu caso):** deja `SUPABASE_JWT_SECRET` **vacío** en
  `backend/.env`. Con solo `SUPABASE_URL`, el backend descarga las llaves
  públicas del endpoint JWKS del proyecto
  (`https://TU-PROYECTO.supabase.co/auth/v1/.well-known/jwks.json`) y
  verifica los tokens con ellas. No hay nada secreto que copiar.
- **Proyecto legacy (HS256):** si tu dashboard sí muestra *JWT Secret*
  (Project Settings → JWT Keys → pestaña *Legacy JWT Secret*), puedes
  pegarlo en `SUPABASE_JWT_SECRET` y el backend usará ese modo.

> En *Project Settings → JWT Keys* puedes confirmar cuál tienes: si la
> pestaña activa es **JWT Signing Keys** con llaves `ECC (P-256)` o `RSA`,
> eres proyecto nuevo → secreto vacío.

### Detalle de la cadena de conexión (la #4)

En *Connection string* verás varias opciones. Usa **Session pooler**
(funciona con IPv4, que es lo común en casa; la "Direct connection" suele
ser solo IPv6 y falla en muchos ISP). Se ve así:

```
postgresql://postgres.abcdefghijk:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:5432/postgres
```

Dos ajustes para nuestra app:

1. Reemplaza `[YOUR-PASSWORD]` por la contraseña del Paso 1.
2. Cambia el prefijo `postgresql://` por **`postgresql+asyncpg://`**
   (el driver async que usa el backend).

Resultado final (ejemplo):

```
postgresql+asyncpg://postgres.abcdefghijk:TuPassword123@aws-0-us-east-1.pooler.supabase.com:5432/postgres
```

> ⚠️ Usa el pooler en **puerto 5432 (Session mode)**, NO el 6543
> (Transaction mode): ese rompe los *prepared statements* de asyncpg.

## Paso 3 — Configurar el login

### Email/contraseña (ya viene activo)

Funciona sin configurar nada. Solo un detalle: por default Supabase exige
**confirmar el correo** antes de poder entrar. Para probar sin fricción:

1. Ve a **Authentication → Sign In / Providers → Email**.
2. Desactiva **Confirm email** (puedes reactivarlo después).

### URL de tu app (necesario para que los links/redirects funcionen)

1. Ve a **Authentication → URL Configuration**.
2. **Site URL:** `http://localhost:5173`

### Google OAuth (opcional — puedes saltarlo y usar solo email)

1. En <https://console.cloud.google.com> crea un proyecto → **APIs y
   servicios → Credenciales → Crear credenciales → ID de cliente de OAuth**.
2. Tipo: *Aplicación web*. En **URIs de redireccionamiento autorizados** pega:
   `https://TU-PROYECTO.supabase.co/auth/v1/callback`
   (la URL exacta te la muestra Supabase en el paso siguiente).
3. Copia el *Client ID* y *Client Secret*.
4. En Supabase: **Authentication → Sign In / Providers → Google** →
   actívalo y pega Client ID y Secret → **Save**.

## Paso 4 — Llenar los archivos `.env`

### `backend/.env` (créalo copiando `backend/.env.example`)

```env
ENV=dev
DATABASE_URL=postgresql+asyncpg://postgres.abcdefghijk:TuPassword123@aws-0-us-east-1.pooler.supabase.com:5432/postgres
SUPABASE_URL=https://TU-PROYECTO.supabase.co
# Vacío en proyectos nuevos (JWT Signing Keys); solo se llena en legacy HS256.
SUPABASE_JWT_SECRET=
SCHEDULER_ENABLED=true
# Opcionales (la app funciona sin ellos):
BANXICO_TOKEN=
COINGECKO_API_KEY=
```

- `SCHEDULER_ENABLED=true` enciende los jobs automáticos (recurrentes,
  cierre de ciclos de tarjeta, tipo de cambio, snapshots de inversiones).
- `BANXICO_TOKEN`: gratis en <https://www.banxico.org.mx/SieAPIRest/service/v1/token>
  — sin él no se descarga el tipo de cambio USD/MXN automático (puedes
  capturar la tasa manualmente al registrar gastos en USD).
- `COINGECKO_API_KEY`: gratis (plan Demo) en <https://www.coingecko.com/en/api>
  — sin él los precios crypto igual funcionan pero con límites más bajos.

### `frontend/.env` (créalo copiando `frontend/.env.example`)

```env
VITE_SUPABASE_URL=https://TU-PROYECTO.supabase.co
VITE_SUPABASE_ANON_KEY=la-anon-key-del-paso-2
```

> No pongas `VITE_API_URL`: en desarrollo el frontend usa el proxy de Vite
> hacia `localhost:8000` automáticamente.

## Paso 5 — Crear las tablas (migraciones)

Desde la carpeta del proyecto:

```powershell
cd backend
python -m uv run alembic upgrade head
```

Esto crea las ~20 tablas (espacios, transacciones, tarjetas, MSI,
inversiones…) **y activa Row-Level Security** como segunda capa de seguridad.
Si termina sin errores, tu base está lista.

> Si ves un error de conexión aquí, el 99% de las veces es la
> `DATABASE_URL`: revisa contraseña, que sea el pooler en puerto **5432**
> y el prefijo `postgresql+asyncpg://`.

## Paso 6 — Arrancar la app

Necesitas dos terminales:

**Terminal 1 — backend:**
```powershell
cd backend
python -m uv run uvicorn app.main:app --reload
```
Queda en `http://localhost:8000` (puedes abrir `http://localhost:8000/docs`
para ver la API).

**Terminal 2 — frontend:**
```powershell
cd frontend
npm install   # solo la primera vez
```
Queda en `http://localhost:5173`.

## Paso 7 — Primer uso

1. Abre <http://localhost:5173> → verás la pantalla de login.
2. **Regístrate** con email y contraseña (o "Continuar con Google" si lo
   configuraste).
3. Al entrar por primera vez la app crea automáticamente tu **espacio
   "Personal"** con categorías y métodos de pago listos para usar.
4. Recorrido sugerido:
   - **Transacciones** → registra tu primer gasto (toma <10 segundos).
   - **Tarjetas** → da de alta tu tarjeta de crédito (solo alias, banco y
     últimos 4 dígitos — nunca el número completo).
   - **MSI** → convierte una compra con tarjeta en meses sin intereses.
   - **Dashboard** → totales del mes, presupuestos y próximos pagos.
   - **Ajustes** → catálogos, gastos recurrentes (suscripciones, renta),
     espacios compartidos e importación de CSV del banco.
   - El botón 🌙/☀️ (arriba a la derecha) cambia entre tema claro y oscuro.

---

## Problemas comunes

| Síntoma | Causa probable | Solución |
|---|---|---|
| Login dice "Falta configurar Supabase" | `frontend/.env` no existe o Vite no lo leyó | Crea el archivo y **reinicia** `npm run dev` |
| `401 Invalid token` en cada request | Proyecto nuevo con `SUPABASE_JWT_SECRET` lleno (o secret legacy mal copiado) | Proyecto nuevo: **vacía** `SUPABASE_JWT_SECRET` y deja solo `SUPABASE_URL`; legacy: re-copia el secret. Reinicia uvicorn |
| `alembic upgrade` no conecta / timeout | URL directa IPv6 o password mal | Usa el **Session pooler** (puerto 5432) y verifica la contraseña |
| Error con `prepared statements` | Usaste el puerto 6543 (transaction mode) | Cambia a puerto **5432** en la URL |
| Registro pide confirmar correo | *Confirm email* activo | Desactívalo (Paso 3) o revisa tu bandeja |
| `No se pudo cargar tu perfil` tras login | Backend apagado o sin `.env` | Verifica la Terminal 1 (`localhost:8000/docs` debe responder) |
| Google OAuth regresa error de redirect | Falta el callback en Google Cloud | Agrega `https://TU-PROYECTO.supabase.co/auth/v1/callback` exacto |

## ¿Qué hace cada credencial? (mapa mental)

```
┌──────────────┐  login (Google/email)   ┌─────────────────┐
│   Frontend    │ ───────────────────────▶ │    Supabase      │
│  localhost:   │   VITE_SUPABASE_URL      │  Auth + Postgres │
│     5173      │   VITE_SUPABASE_ANON_KEY └─────────────────┘
│               │                                ▲    ▲
│  datos SIEMPRE│  Authorization: Bearer JWT     │    │ DATABASE_URL
│  vía FastAPI  │ ────────────────────────▶ ┌────┴────┴───┐
└──────────────┘                            │   Backend    │
                                            │ localhost:   │ verifica el JWT con el
                                            │    8000      │ JWKS público del proyecto
                                            └─────────────┘ (o el secret legacy)
```
