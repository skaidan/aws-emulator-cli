# Roadmap

Plan de evolución de `awsemu`. Cada versión tiene un objetivo claro; dentro de cada una, las tareas están ordenadas por prioridad. Es un documento vivo: se ajusta según lo que aprendamos usando el CLI contra el emulador real.

Leyenda: ✅ hecho · 🚧 en curso · ⬜ pendiente

---

## v0.1 — Base ✅

Objetivo: que arrancar, conectar y explorar el emulador sea un comando cada cosa.

- ✅ `start` / `stop` / `restart` / `status` / `logs` con el binario nativo o con Docker
- ✅ `env` (bash, zsh, fish, PowerShell, dotenv), `exec`, `shell`, `aws`, `whoami`
- ✅ `overview` de varios servicios en una pantalla
- ✅ Comandos de S3, SQS y DynamoDB (con JSON normal)
- ✅ `doctor`, `image build`, `config telemetry`
- ✅ Tests con un emulador falso y clientes boto3 simulados; CI en Linux

---

## v0.2 — Validado contra el emulador real

Objetivo: confiar en que todo funciona contra el emulador de verdad, en todos los sistemas.

- ⬜ **Tests de integración reales en CI**: un job que instale el `.deb` oficial en Ubuntu, arranque el emulador y ejecute S3, SQS, DynamoDB y `overview` contra él. Marcarlos con `@pytest.mark.real` para poder lanzarlos también en local.
- ⬜ **Parada limpia en Windows**: en Windows, `os.kill(SIGTERM)` cierra el proceso a la fuerza y el emulador no llega a borrar sus ficheros. Hay que enviar `CTRL_BREAK_EVENT` al grupo de procesos y añadir un test.
- ⬜ **CI en macOS y Windows**: generar el certificado del emulador falso con Python en vez de con `openssl -addext`, porque LibreSSL en macOS no siempre lo soporta.
- ⬜ **Soporte de `--port 0`**: leer el puerto real de la línea de arranque (`endpoint_url`) y guardar el estado con ese puerto.
- ⬜ **Logs de Docker persistentes**: con `--rm`, los logs se pierden al parar. Hay que volcarlos a `~/.aws/emulator-cli/<puerto>/emulator.log` igual que en modo nativo.
- ⬜ **Mejores errores**: traducir `AccessDenied` ("Sign the request with the emulator credentials"), `UnknownService` y los errores de TLS por certificado caducado a mensajes con solución concreta.

## v0.3 — Más servicios

Objetivo: cubrir los servicios que más se usan en tests de aplicaciones.

- ⬜ **SNS**: `topics`, `create`, `publish`, `subscribe` (con atajo `--to-sqs COLA` que crea la suscripción y la política).
- ⬜ **Lambda**: `ls`, `deploy` (desde carpeta o zip), `invoke` con payload JSON y salida legible, `logs`.
- ⬜ **Secrets Manager y SSM Parameter Store**: `get`, `put`, `ls`, `rm`.
- ⬜ **EventBridge**: `buses`, `rules`, `put-event`.
- ⬜ **Kinesis y Step Functions**: listados, `put-record` y `start-execution` con seguimiento del estado.
- ⬜ **`awsemu describe <ARN>`**: muestra cualquier recurso a partir de su ARN, sin tener que saber qué servicio es.

## v0.4 — Estado reproducible (seeds)

Objetivo: arrancar siempre con los mismos datos. El emulador lo guarda todo en memoria y no tiene ruta de reset, así que esto tiene que resolverlo el CLI.

- ⬜ **`awsemu seed apply seed.yaml`**: fichero declarativo con buckets (y objetos desde carpetas locales), colas con sus DLQ, tablas con items, secretos y parámetros. Debe ser idempotente.
- ⬜ **`awsemu start --seed seed.yaml`** y **`awsemu reset --seed`**: reiniciar y volver a cargar los datos en un solo paso.
- ⬜ **`awsemu snapshot export > seed.yaml`**: volcar el estado actual a un seed, para capturar un escenario creado a mano.
- ⬜ Validación del fichero con mensajes claros (línea y campo exactos).

## v0.5 — Integración con proyectos y CI

Objetivo: que un proyecto declare su emulador y cualquiera lo levante con `awsemu up`.

- ⬜ **`awsemu.toml` por proyecto**: puerto, modo, auth, seed, extras de SDK. `awsemu up` / `down` lo leen.
- ⬜ **Plugin de pytest**: fixture `aws_emulator` que arranca una instancia por sesión (o por test, en un puerto libre), aplica el seed y configura el entorno.
- ⬜ **GitHub Action** (`skaidan/aws-emulator-cli@v1`): instala el emulador y el CLI, arranca la instancia y exporta las variables para los pasos siguientes.
- ⬜ **`awsemu compose`**: genera el servicio de `docker compose` con la configuración segura (puerto solo en `127.0.0.1`, volumen y límite de memoria).

## v0.6 — Experiencia interactiva

Objetivo: explorar el emulador sin recordar comandos.

- ⬜ **Autocompletado** de shell (`awsemu completion bash|zsh|fish`), con nombres de buckets, colas y tablas.
- ⬜ **TUI** (`awsemu ui`, con Textual): árbol de servicios y recursos, vista de items y mensajes, logs en vivo y acciones rápidas (crear, borrar, purgar).
- ⬜ **`awsemu watch`**: muestra en directo las llamadas a la API que recibe el emulador, a partir de su log.
- ⬜ **Información de fidelidad**: mostrar la puntuación de fidelidad por servicio que publica cada release del emulador, para saber de antemano qué está bien soportado.

## v1.0 — Distribución estable

Objetivo: instalar y actualizar en cualquier sitio con un comando.

- ⬜ Publicación en **PyPI** (`pipx install aws-emulator-cli`) con releases automáticas desde tags.
- ⬜ **Homebrew tap** y binarios autónomos (PyInstaller) para quien no tenga Python.
- ⬜ `CHANGELOG.md`, versionado semántico y promesa de estabilidad para la salida `--json`.
- ⬜ Web de documentación (MkDocs) con guías: "tests de integración con pytest", "CI con GitHub Actions" y "Node y Java contra el emulador".

---

## Ideas sin versión asignada

- Varias regiones: el emulador solo admite una región por instancia, así que `awsemu` podría gestionar un grupo de instancias, una por región.
- Perfil de AWS CLI con nombre (`--profile emulator`) como alternativa a exportar variables.
- Integración con Terraform y CDK (`awsemu exec -- terraform apply` con el `provider` ya configurado).

¿Tienes una idea o necesitas algo antes? Abre un issue.
