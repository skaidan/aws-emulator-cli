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

## v0.2 — Validado contra el emulador real ✅

Objetivo: confiar en que todo funciona contra el emulador de verdad, en todos los sistemas.

- ✅ **Tests de integración reales en CI**: el job `real-emulator` descarga el `.deb` oficial, verifica su firma GPG y ejecuta `tests/test_real.py` (S3, SQS, DynamoDB, `overview`, `exec`, `restart`). En local: `AWSEMU_REAL_TESTS=1 pytest -m real`.
- ✅ **Parada limpia en Windows**: se envía Ctrl+Break al grupo de procesos del emulador. Si tras una parada forzada (o en Windows) quedan ficheros en `~/.aws/emulator/<puerto>/`, `awsemu` los borra.
- ✅ **CI en Linux, macOS y Windows**: el emulador falso genera su certificado con `cryptography`.
- ✅ **Soporte de `--port 0`**: el puerto real se lee de la línea de arranque.
- ✅ **Logs persistentes**: también en Docker, y legibles después de parar.
- ✅ **Mejores errores**: pistas concretas para `AccessDenied`, `SignatureDoesNotMatch`, peticiones sin firmar, `UnknownService`, reloj desfasado, operaciones no emuladas y TLS.
- ✅ `AWSEMU_BINARY` para usar un binario que no esté en el `PATH`.

## v0.3 — Más servicios ✅

Objetivo: cubrir los servicios que más se usan en tests de aplicaciones. Todo probado contra el emulador real en CI.

- ✅ **SNS**: `ls`, `create`, `publish`, `subscribe` (con `--to-sqs COLA`, que crea la suscripción y la política de la cola, y `--to-lambda`).
- ✅ **Lambda**: `ls`, `deploy` (desde carpeta, fichero o zip; adivina handler y runtime), `invoke` con payload JSON y su log, `logs`, `info`, `rm`.
- ✅ **Secrets Manager y SSM Parameter Store**: `put`, `get`, `ls`, `rm` (y `info` en secretos).
- ✅ **EventBridge**: `rule` con su destino y permisos en un paso (`--to-sqs`, `--to-lambda`, `--to-sns`), `put`, `rules`, `buses`, `rm`.
- ✅ **Kinesis**: `create`, `put`, `read` (todos los shards, `--follow`), `ls`, `rm`.
- ✅ **Step Functions**: `deploy`, `start` (espera y muestra salida o causa del fallo), `executions`, `rm`.
- ✅ **`awsemu describe <ARN>`** para 12 servicios.

Aprendido en CI: el emulador no envía la salida de Lambda a CloudWatch Logs; `lambda invoke` muestra el log de cada invocación.

## v0.4 — Estado reproducible (seeds) ✅

Objetivo: arrancar siempre con los mismos datos. El emulador lo guarda todo en memoria y no tiene ruta de reset, así que esto lo resuelve el CLI.

- ✅ **`awsemu seed apply seed.yaml`**: fichero declarativo con buckets (y objetos en línea, JSON o desde carpetas locales), colas con sus DLQ, tablas con items (en línea o desde fichero), temas con suscripciones, secretos y parámetros. Idempotente: crea, actualiza o deja igual, y nunca borra.
- ✅ **`awsemu start --seed`** y **`awsemu reset --seed`**: el seed se valida antes de arrancar o parar nada.
- ✅ **`awsemu seed export`**: vuelca el estado actual a un seed (secretos opcionales, binarios a una carpeta).
- ✅ **Validación** con línea y campo exactos, sugerencias para campos mal escritos y `awsemu seed validate`.
- ✅ Ejemplo completo en `examples/seed.yaml`, validado en los tests y aplicado contra el emulador real en CI.

Fuera de esta versión: funciones Lambda, reglas de EventBridge, streams de Kinesis y máquinas de Step Functions en el seed.

## v0.5 — Integración con proyectos y CI ✅

Objetivo: que un proyecto declare su emulador y cualquiera lo levante con `awsemu up`.

- ✅ **`awsemu.toml` por proyecto** (o `[tool.awsemu]` en `pyproject.toml`): puerto, modo, auth, telemetría, `idle_timeout`, seed, extras de SDK, imagen y memoria. `awsemu init` lo crea (con un puerto propio del proyecto), `awsemu up` arranca y aplica el seed, `awsemu down` lo para. Precedencia: flag > entorno > proyecto > defecto.
- ✅ **Plugin de pytest**: fixtures `aws_emulator` (sesión, puerto libre, seed, entorno) y `aws_emulator_fresh` (reinicio por test), con opciones `--awsemu-*` e ini.
- ✅ **GitHub Action** (`uses: skaidan/aws-emulator-cli@v0.5.0`): instala el paquete verificado y `awsemu`, arranca, aplica el seed y exporta las variables.
- ✅ **`awsemu compose`**: genera el servicio de Docker Compose con la configuración segura.
- ✅ CI con el modo Docker real (`image build`, `start --docker`, `compose`) y con la propia Action.

Aprendido en CI: el modo Docker funcionó a la primera; el plugin tenía un bug de orden con `HOME` que solo se veía con el emulador real (corregido y cubierto por un test).

## v0.6 — Experiencia interactiva

Objetivo: explorar el emulador sin recordar comandos.

- ⬜ **Autocompletado** de shell (`awsemu completion bash|zsh|fish`), con nombres de buckets, colas y tablas.
- ⬜ **TUI** (`awsemu ui`, con Textual): árbol de servicios y recursos, vista de items y mensajes, logs en vivo y acciones rápidas (crear, borrar, purgar).
- ⬜ **`awsemu watch`**: muestra en directo las llamadas a la API que recibe el emulador, a partir de su log.
- ⬜ **Información de fidelidad**: mostrar la puntuación de fidelidad por servicio que publica cada release del emulador, para saber de antemano qué está bien soportado.

## v1.0 — Distribución estable

Objetivo: instalar y actualizar en cualquier sitio con un comando.

- ✅ Releases automáticas en GitHub desde `CHANGELOG.md` (wheel y sdist adjuntos).
- ⬜ Publicación en **PyPI** (`pipx install aws-emulator-cli`).
- ⬜ **Homebrew tap** y binarios autónomos (PyInstaller) para quien no tenga Python.
- ⬜ `CHANGELOG.md`, versionado semántico y promesa de estabilidad para la salida `--json`.
- ✅ Documentación en `docs/`: primeros pasos, servicios, tests y CI, solución de problemas, arquitectura y referencia generada desde el código.
- ⬜ Web de documentación (MkDocs) con guías: "tests de integración con pytest", "CI con GitHub Actions" y "Node y Java contra el emulador".

---

## Ideas sin versión asignada

- Varias regiones: el emulador solo admite una región por instancia, así que `awsemu` podría gestionar un grupo de instancias, una por región.
- Perfil de AWS CLI con nombre (`--profile emulator`) como alternativa a exportar variables.
- Integración con Terraform y CDK (`awsemu exec -- terraform apply` con el `provider` ya configurado).

¿Tienes una idea o necesitas algo antes? Abre un issue.
