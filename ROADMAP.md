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

## v0.6 — Experiencia interactiva ✅

Objetivo: explorar el emulador sin recordar comandos.

- ✅ **Autocompletado** (`awsemu completion bash|zsh|fish`), con los nombres reales de buckets (y rutas), colas, tablas, temas, funciones, secretos, parámetros, streams, máquinas de estados y reglas.
- ✅ **Interfaz en la terminal** (`awsemu ui`, con Textual, extra `ui`): árbol de servicios y recursos, detalle de cada uno (sin mostrar valores secretos), refresco manual y automático.
- ✅ **`awsemu watch`**: cambios en directo de los recursos (creados, borrados, mensajes, items, objetos).
- ✅ **`awsemu fidelity`**: puntuación por servicio publicada con cada release del emulador, para tu versión instalada, y detalle de las pruebas que fallan.

Aprendido en CI: el emulador no registra las llamadas a la API (ni con `RUST_LOG=debug`), así que `watch` muestra el efecto en los recursos en lugar de las llamadas. Las puntuaciones están en un `scores.json.gz` adjunto a cada release, con el resultado de cada prueba y los servicios que llama.

## v0.7 — Preparar la publicación

Objetivo: decidir lo que es difícil de cambiar una vez que otros instalan y usan `awsemu`.

- ⬜ **Preparar el cambio de nombre** (el nombre se decide al final, en v1.0): hoy "aws-emulator-cli" aparece 37 veces en 13 ficheros. Reunirlo en pocos sitios y añadir un script que lo cambie de una vez (paquete, repositorio, URLs de la documentación y de la GitHub Action) y compruebe que no queda ninguna referencia antigua.
- ⬜ **Documentación en inglés.** README y guías principales en inglés, con la versión en español enlazada (o al revés), para llegar a más gente. Los mensajes del CLI ya están en inglés.
- ⬜ **Salida estable.** Fijar y documentar el formato de `--json` de cada comando y los códigos de salida (0, 1, 2, 3), con tests que detecten cambios accidentales; después de publicar, cambiarlos rompería scripts ajenos.
- ⬜ Revisión general de mensajes, ayudas y valores por defecto antes de congelarlos.

## v0.8 — ¿Funcionará mi proyecto con el emulador?

Objetivo: responder antes de empezar, y actualizar el emulador sin sustos.

- ⬜ **`awsemu check`**: busca en tu código e infraestructura (boto3, SDK de Node/Java/Go, Terraform, CloudFormation/CDK) las operaciones de AWS que usas y las cruza con las pruebas de fidelidad que fallan, usando el fichero de puntuaciones y el `manifest.jsonl` del repositorio de pruebas, que relaciona cada prueba con sus operaciones. Resultado del estilo: "usas `dynamodb:TransactWriteItems`: 2 diferencias conocidas, estas".
- ⬜ **`awsemu fidelity --compare vX`**: qué ha mejorado y qué ha empeorado entre dos releases, solo en los servicios que usas.
- ⬜ **`awsemu install [--version]`**: instalar o fijar una versión concreta del emulador (paquete en Linux, imagen en Docker), y `emulator_version` en `awsemu.toml` para que el equipo y la CI usen la misma. La GitHub Action también aceptará la versión.

## v0.9 — Proxy: ver las llamadas e inyectar fallos

Objetivo: lo que el emulador no da. No registra las llamadas a la API (comprobado en CI, v0.6) y, según los analistas, no simula throttling ni caídas.

- ⬜ **`awsemu proxy`**: un proxy local entre tu aplicación y el emulador, con su propio certificado, que registra cada llamada (servicio, operación, recurso, latencia, código de error).
- ⬜ **`awsemu watch --calls`** y una vista de llamadas en `awsemu ui`, alimentadas por el proxy.
- ⬜ **Inyección de fallos**: reglas como "`ThrottlingException` en el 10 % de las llamadas a DynamoDB" o "500 ms de latencia en S3", configurables por comando y en `awsemu.toml`, para probar reintentos y resiliencia.
- ⬜ Integración con el plugin de pytest (fixture para activar fallos en un test concreto).

## v0.10 — Completar lo que ya existe

Objetivo: cerrar los huecos conocidos de lo ya hecho.

- ⬜ **Seeds con más servicios**: funciones Lambda (desde código local), reglas de EventBridge, streams de Kinesis y máquinas de Step Functions, también en `seed export`.
- ⬜ **`awsemu snapshot save/restore`**: guardar y recuperar un escenario completo (el emulador no tiene snapshots), sobre la base de `seed export` y `reset --seed`.
- ⬜ **Herramientas de infraestructura y otros lenguajes, probados en CI**: Terraform, CDK, y los SDK de Node, Java y Go contra el emulador, con guías y ejemplos. Hoy solo está probado Python.

## v0.11 — Agentes de IA

Objetivo: que un agente de programación pruebe su código contra el emulador sin tocar AWS.

- ⬜ **Servidor MCP de `awsemu`**: herramientas para arrancar y parar el emulador, aplicar seeds, consultar recursos, ver la fidelidad de un servicio y leer las llamadas del proxy.
- ⬜ Guía para usarlo con agentes, junto al *skill* `aws-emulator` que menciona la documentación de AWS.

## v1.0 — Distribución estable

Objetivo: instalar y actualizar en cualquier sitio con un comando.

- ⬜ **Nombre definitivo, justo antes de publicar.** "aws-emulator-cli" usa la marca AWS; para un proyecto no oficial en PyPI y Homebrew puede causar problemas o confundirse con algo oficial. Elegir el nombre, comprobar que está libre en PyPI, Homebrew y GitHub, aplicarlo con el script de v0.7 y publicar enseguida, para que no lo ocupe nadie entre medias.
- ✅ Releases automáticas en GitHub desde `CHANGELOG.md` (wheel y sdist adjuntos).
- ⬜ Publicación en **PyPI** (`pipx install aws-emulator-cli`).
- ⬜ **Homebrew tap** y binarios autónomos (PyInstaller) para quien no tenga Python.
- ⬜ Versionado semántico y promesa de estabilidad (la salida se fija en v0.7).
- ✅ Documentación en `docs/`: primeros pasos, servicios, tests y CI, solución de problemas, arquitectura y referencia generada desde el código.
- ⬜ Web de documentación (MkDocs) con guías: "tests de integración con pytest", "CI con GitHub Actions" y "Node y Java contra el emulador".

---

## Ideas sin versión asignada

- Varias regiones: el emulador solo admite una región por instancia, así que `awsemu` podría gestionar un grupo de instancias, una por región.
- Perfil de AWS CLI con nombre (`--profile emulator`) como alternativa a exportar variables.
- Integración con Terraform y CDK (`awsemu exec -- terraform apply` con el `provider` ya configurado).

¿Tienes una idea o necesitas algo antes? Abre un issue.
