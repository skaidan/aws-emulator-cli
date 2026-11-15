# Configuración por proyecto (`awsemu.toml`)

Un fichero `awsemu.toml` en tu proyecto guarda cómo quieres el emulador: puerto, modo, seed, etc. Cualquier comando de `awsemu` ejecutado en esa carpeta (o en una subcarpeta) lo usa, igual que el [plugin de pytest](testing.md#plugin-de-pytest).

```bash
awsemu init     # crea awsemu.toml
awsemu up       # arranca el emulador del proyecto (si no lo está) y aplica su seed
awsemu down     # lo para
```

## El fichero

```toml
# awsemu.toml
port = 9343                # cada proyecto en su puerto: varios a la vez sin chocar
mode = "auto"              # auto | native | docker
auth = true                # false = acepta peticiones sin firmar
telemetry = false
idle_timeout = 3600        # se para solo tras una hora sin llamadas
seed = "tests/seed.yaml"   # relativo a este fichero
sdk = ["node"]             # node | java | rust | dotnet: confiar en el certificado en esos SDK
image = "aws-emulator"     # imagen de Docker
memory = "2g"              # límite de memoria en Docker
```

Todas las claves son opcionales.

| Clave | Tipo | Para qué | Por defecto |
| --- | --- | --- | --- |
| `port` | entero | Puerto de la instancia; lo usan todos los comandos | 9297 |
| `mode` | `auto` / `native` / `docker` | Cómo arrancarla | `auto` (binario si está, si no Docker) |
| `auth` | booleano | Exigir peticiones firmadas | `true` |
| `telemetry` | booleano | Telemetría del emulador para esta instancia | lo que diga `config.toml` del emulador |
| `idle_timeout` | entero (segundos) | Parada automática por inactividad | sin límite |
| `seed` | ruta | Seed que aplican `awsemu up` y el plugin de pytest | ninguno |
| `sdk` | lista | Extras de certificado en `env`, `exec` y `shell` | ninguno |
| `image` | texto | Imagen de Docker | `aws-emulator` |
| `memory` | texto | Límite de memoria en Docker | `2g` |

### En `pyproject.toml`

En proyectos Python puedes usar una tabla `[tool.awsemu]` en lugar de un fichero aparte:

```toml
[tool.awsemu]
port = 9343
seed = "tests/seed.yaml"
telemetry = false
```

## Dónde lo busca

Desde la carpeta actual hacia arriba, `awsemu` usa el primer `awsemu.toml` que encuentre, o el primer `pyproject.toml` que tenga una tabla `[tool.awsemu]`. Para usar otro fichero: `AWSEMU_CONFIG=/ruta/al/fichero.toml`.

```bash
awsemu config show      # qué fichero se está usando y con qué valores
awsemu doctor           # incluye una fila "project"
```

## Precedencia

De más a menos prioridad:

1. Lo que pongas en el comando (`--port 9400`, `--no-auth`, `--docker`, `--seed …`, `--sdk …`).
2. Variables de entorno (`AWSEMU_PORT`).
3. `awsemu.toml` / `[tool.awsemu]`.
4. Valores por defecto.

## `awsemu init`

Crea `awsemu.toml` en la carpeta actual con valores razonables (`telemetry = false`, `idle_timeout = 3600`) y comentarios para el resto.

- **Puerto:** si no pasas `--port`, elige uno entre 9300 y 9399 a partir del nombre de la carpeta, así varios proyectos pueden tener su emulador encendido a la vez. Con `awsemu --port 9400 init` usa ese.
- **Seed:** si existe `tests/seed.yaml`, `seed.yaml` o `awsemu-seed.yaml`, lo referencia. También con `--seed RUTA`.
- No sobrescribe un fichero existente salvo con `--force`.

## `awsemu up` y `awsemu down`

`up` deja el emulador del proyecto listo:

- Si no está en marcha, lo arranca con la configuración del proyecto.
- Aplica el seed (el del proyecto, el de `--seed`, o ninguno con `--no-seed`). Como [`seed apply`](seeds.md#qué-hace-apply) se puede repetir, ejecutar `up` con el emulador ya encendido solo añade o actualiza lo que falte.

`down` lo para (como `awsemu stop`; `--all` para todas las instancias).

Un flujo típico de trabajo:

```bash
cd mi-proyecto
awsemu up
eval "$(awsemu env)"
npm run dev                  # o lo que sea: ya habla con el emulador
awsemu reset --seed tests/seed.yaml   # volver al estado inicial cuando quieras
awsemu down
```

## Errores

Un `awsemu.toml` con errores detiene cualquier comando (código 2) con un mensaje concreto:

```
✗ /home/ana/mi-proyecto/awsemu.toml: 'port' must be int; unknown setting 'mdoe' (did you mean 'mode'?)
  Fix the file, or set AWSEMU_CONFIG to another one.
```

Hay un ejemplo en [`examples/awsemu.toml`](../examples/awsemu.toml).
