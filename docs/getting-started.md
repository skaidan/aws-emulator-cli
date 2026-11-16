# Primeros pasos

## 1. Instalar `awsemu`

Necesitas Python 3.10 o superior.

```bash
pipx install git+https://github.com/skaidan/aws-emulator-cli
# o, desde una release concreta:
pipx install https://github.com/skaidan/aws-emulator-cli/releases/download/v0.6.0/aws_emulator_cli-0.6.0-py3-none-any.whl
```

Opcional: autocompletado (también de los nombres de tus buckets, colas, tablas…) y la interfaz en la terminal:

```bash
echo 'eval "$(awsemu completion bash)"' >> ~/.bashrc    # zsh: completion zsh; fish: ver docs/explore.md
pipx install --force 'aws-emulator-cli[ui] @ git+https://github.com/skaidan/aws-emulator-cli'
```

Comprueba qué tienes y qué falta:

```bash
awsemu doctor
```

## 2. Elegir cómo ejecutar el emulador

`awsemu` no incluye el emulador: lo ejecuta. Hay dos formas, y `awsemu start` elige sola (primero el binario nativo, si no, Docker).

### Nativo (Linux)

Instala el paquete oficial. Ejemplo para Debian/Ubuntu en x86_64:

```bash
curl -fsSLo aws-emulator.deb https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS/latest/aws-emulator_amd64.deb
sudo apt-get install -y ./aws-emulator.deb
aws-emulator -v
```

Para RPM o ARM, y para verificar la firma del paquete, mira la [guía oficial de instalación en Linux](https://docs.aws.amazon.com/emulator/latest/userguide/getting-started-linux.html).

Si el binario no está en el `PATH`, díselo a `awsemu`:

```bash
export AWSEMU_BINARY=/ruta/a/aws-emulator
```

### Docker (macOS, Windows o Linux)

AWS no publica una imagen; `awsemu` la construye con la receta oficial (detecta si tu máquina es x86_64 o ARM):

```bash
awsemu image build
awsemu image dockerfile   # para ver el Dockerfile que usa
```

¿Prefieres Docker Compose? `awsemu compose -o compose.emulator.yaml` genera el servicio con la misma configuración (ver [Tests y CI](testing.md#docker-compose)).

## 3. Arrancar

```bash
awsemu start
```

`awsemu` lanza el emulador en segundo plano, espera a que responda en `https://127.0.0.1:9297/__admin/health` y te dice cómo seguir. Opciones útiles:

| Quiero… | Comando |
| --- | --- |
| Forzar Docker o nativo | `awsemu start --docker` / `--native` |
| Otro puerto | `awsemu --port 9300 start` |
| Que el sistema elija el puerto | `awsemu --port 0 start` (solo nativo) |
| Que se pare solo si no se usa | `awsemu start --idle-timeout 600` |
| Aceptar peticiones sin firmar | `awsemu start --no-auth` |
| Sin telemetría | `awsemu start --no-telemetry` o `awsemu config telemetry off` |
| Verlo en primer plano | `awsemu start -f` |
| Arrancar con datos | `awsemu start --seed seed.yaml` (ver [Seeds](seeds.md)) |

```bash
awsemu status          # ¿está sano?
awsemu logs -f         # su log, legible
awsemu stop            # parada limpia
awsemu reset           # reinicio = estado vacío (el emulador guarda todo en memoria)
awsemu reset --seed seed.yaml   # estado vacío + tus datos de partida
```

## 4. Conectar tus herramientas

El emulador genera claves y un certificado nuevos en cada arranque, en `~/.aws/emulator/<puerto>/`. `awsemu env` exporta las variables que apuntan a esos ficheros:

```bash
eval "$(awsemu env)"
aws sts get-caller-identity   # Account: 000000000000 → estás en el emulador
```

| Shell | Comando |
| --- | --- |
| bash / zsh | `eval "$(awsemu env)"` |
| fish | `awsemu env --shell fish \| source` |
| PowerShell | `awsemu env --shell powershell \| iex` |
| fichero `.env` | `awsemu env --shell dotenv > .env.emulator` |
| deshacer | `eval "$(awsemu env --unset)"` |

`awsemu env` también quita `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` y `AWS_PROFILE`: si se quedaran, tendrían prioridad y el emulador rechazaría las peticiones.

Algunos SDK no leen `AWS_CA_BUNDLE`. Añade lo que necesiten con `--sdk`:

```bash
eval "$(awsemu env --sdk node)"   # NODE_EXTRA_CA_CERTS
eval "$(awsemu env --sdk java)"   # JAVA_TOOL_OPTIONS con truststore.p12
eval "$(awsemu env --sdk rust)"   # SSL_CERT_FILE (también para .NET: --sdk dotnet)
```

Sin tocar tu shell:

```bash
awsemu exec -- npm test          # un comando con el entorno ya configurado
awsemu aws s3 ls                 # el AWS CLI apuntando al emulador
awsemu shell                     # una sub-shell conectada
```

## 5. Explorar

```bash
awsemu overview        # qué hay en S3, SQS, DynamoDB, SNS, Lambda, Secrets, SSM…
awsemu s3 mb fotos
awsemu sqs create trabajos
```

Sigue con la [guía de servicios](services.md), o explora con `awsemu ui`, `awsemu watch` y `awsemu fidelity` ([Explorar el emulador](explore.md)).

## En un proyecto

Si trabajas siempre con la misma configuración, guárdala en el proyecto:

```bash
awsemu init      # crea awsemu.toml con un puerto propio y tu seed
awsemu up        # arranca (si hace falta) y aplica el seed
awsemu down
```

Ver [Configuración por proyecto](project-config.md).

## Varias instancias

Cada instancia vive en su puerto, con sus propios ficheros y recursos. Usa `--port` (o `AWSEMU_PORT`) en cualquier comando:

```bash
awsemu --port 9300 start
AWSEMU_PORT=9300 awsemu overview
awsemu status --all
awsemu stop --all
```
