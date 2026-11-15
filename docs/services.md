# Guía de servicios

[Vista general](#vista-general) · [S3](#s3) · [SQS](#sqs) · [DynamoDB](#dynamodb) · [SNS](#sns) · [Lambda](#lambda) · [Secrets Manager](#secrets-manager) · [SSM](#ssm-parameter-store) · [EventBridge](#eventbridge) · [Kinesis](#kinesis) · [Step Functions](#step-functions) · [describe](#cualquier-recurso-por-su-arn)

Todos los comandos de servicio hablan con el emulador del puerto seleccionado (`--port`, por defecto 9297), con su endpoint, su certificado y sus claves configurados de forma explícita. Aunque tu shell tenga credenciales reales de AWS, **estos comandos nunca llaman a AWS**.

Casi todos aceptan `--json` para usarlos en scripts, y los que borran piden confirmación salvo con `--yes`.

Para operaciones que `awsemu` no cubre, usa el AWS CLI apuntando al emulador: `awsemu aws <servicio> <operación> ...`.

## Vista general

```bash
awsemu overview                 # solo los servicios con algo dentro
awsemu overview --all           # también los vacíos
awsemu overview -s s3 -s sqs    # solo algunos
awsemu overview --json
```

Revisa S3, SQS, DynamoDB, SNS, Lambda, Secrets Manager, SSM, Kinesis, EventBridge, Step Functions, CloudWatch Logs e IAM. Si un servicio falla, lo indica en su fila y sigue con los demás.

## S3

```bash
awsemu s3 mb fotos                         # crear bucket(s)
awsemu s3 put ./gato.jpg fotos/            # subir; con / al final usa el nombre del fichero
awsemu s3 put ./web fotos/sitio/           # subir una carpeta entera
awsemu s3 ls                               # buckets
awsemu s3 ls fotos                         # un nivel, con "carpetas"
awsemu s3 ls fotos -r                      # todo, recursivo
awsemu s3 cat fotos/notas.txt              # a la salida estándar
awsemu s3 get fotos/gato.jpg ./descargas/
awsemu s3 presign fotos/gato.jpg --expires 600
awsemu s3 rm fotos/gato.jpg
awsemu s3 rm -r fotos/sitio/ --yes         # todo un prefijo
awsemu s3 rb fotos --force --yes           # vaciar y borrar el bucket
```

Los buckets se pueden escribir como `fotos/clave` o `s3://fotos/clave`.

## SQS

```bash
awsemu sqs create trabajos-dlq
awsemu sqs create trabajos --dlq trabajos-dlq --max-receive 3 --visibility-timeout 30
awsemu sqs create pedidos --fifo --dedup   # añade .fifo si falta

awsemu sqs send trabajos '{"id": 1}' -a tipo=alta
echo '{"id": 2}' | awsemu sqs send trabajos --file -
awsemu sqs send pedidos.fifo '{"id": 3}' --group cliente-7

awsemu sqs ls                              # colas con mensajes visibles / en vuelo / retrasados
awsemu sqs receive trabajos                # los mensajes se quedan en la cola…
awsemu sqs receive trabajos --delete       # …salvo con --delete
awsemu sqs info trabajos                   # todos los atributos
awsemu sqs purge trabajos --yes
awsemu sqs rm trabajos --yes
```

Las colas se pueden indicar por nombre o por URL.

## DynamoDB

Los items se escriben y se muestran como JSON normal. `awsemu` hace la conversión al formato de DynamoDB (`{"S": ...}`, `{"N": ...}`) por ti.

```bash
awsemu ddb create usuarios --pk id                      # clave de partición tipo S
awsemu ddb create eventos --pk usuario --sk fecha:N     # con clave de ordenación numérica

awsemu ddb put usuarios '{"id": "u1", "nombre": "Ana", "edad": 30, "tags": ["admin"]}'
awsemu ddb put usuarios --file usuarios.json            # un objeto o una lista (por lotes de 25)

awsemu ddb get usuarios '{"id": "u1"}'
awsemu ddb scan usuarios                                # tabla legible
awsemu ddb scan usuarios -n 0 --json                    # todo, en JSON
awsemu ddb delete usuarios '{"id": "u1"}'
awsemu ddb ls
awsemu ddb describe usuarios
awsemu ddb drop usuarios --yes
```

Tipos: texto → `S`, número → `N`, `true/false` → `BOOL`, `null` → `NULL`, lista → `L`, objeto → `M`. Los números con decimales se guardan sin perder precisión.

## SNS

```bash
awsemu sns create pedidos
awsemu sns create pedidos.fifo --fifo

# Entregar a una cola SQS: awsemu crea la suscripción Y la política de la cola.
awsemu sqs create eventos-pedidos
awsemu sns subscribe pedidos --to-sqs eventos-pedidos --raw   # --raw: sin el sobre JSON de SNS

# Entregar a una función Lambda: añade el permiso de invocación.
awsemu sns subscribe pedidos --to-lambda procesar-pedido

# Con filtro
awsemu sns subscribe pedidos --to-sqs solo-altas --filter '{"tipo": ["alta"]}'

awsemu sns publish pedidos '{"pedido": 42}' --subject nuevo -a tipo=alta
awsemu sns ls                    # temas con sus destinos
awsemu sns subs pedidos
awsemu sns unsubscribe arn:aws:sns:us-east-1:000000000000:pedidos:...
awsemu sns rm pedidos --yes
```

Flujo completo SNS → SQS:

```bash
awsemu sns create pedidos
awsemu sqs create eventos
awsemu sns subscribe pedidos --to-sqs eventos --raw
awsemu sns publish pedidos '{"pedido": 42}'
awsemu sqs receive eventos --delete      # → {"pedido": 42}
```

## Lambda

```bash
# hola.py
# def handler(event, context):
#     return {"saludo": f"hola {event.get('nombre', 'mundo')}"}

awsemu lambda deploy hola ./hola.py                    # crea la función
awsemu lambda invoke hola '{"nombre": "Ana"}'          # respuesta + log
awsemu lambda invoke hola '{"nombre": "Ana"}' --raw    # solo la respuesta (para scripts)
awsemu lambda deploy hola ./hola.py                    # la segunda vez, actualiza el código
```

`deploy` acepta una carpeta (se empaqueta su contenido, sin `__pycache__`, `.git`, `.venv`…), un fichero suelto o un `.zip` ya hecho. Si no indicas `--handler` y `--runtime`, los adivina:

| Código | Handler | Runtime |
| --- | --- | --- |
| `app.py` con `def handler(...)` | `app.handler` | `python3.12` |
| `lambda_function.py` con `def lambda_handler(...)` | `lambda_function.lambda_handler` | `python3.12` |
| `index.mjs` con `export const handler` | `index.handler` | `nodejs20.x` |
| `index.js` con `exports.handler` | `index.handler` | `nodejs20.x` |

Si no pasas `--role`, crea (una vez) el rol `awsemu-lambda-role` con la política de confianza de Lambda.

```bash
awsemu lambda deploy api ./src --handler app.main --runtime python3.13 \
    -e STAGE=local -e TABLE=usuarios --timeout 30 --memory 512
awsemu lambda invoke api --file evento.json
awsemu lambda invoke api '{}' --async          # sin esperar el resultado
awsemu lambda logs api -f                      # logs de CloudWatch (/aws/lambda/api), ver nota
awsemu lambda info api
awsemu lambda ls
awsemu lambda rm api --yes
```

`invoke` termina con código 1 si la función lanza un error, para que los scripts lo detecten.

> **Dónde ver lo que imprime una función.** El emulador no envía la salida de Lambda a CloudWatch Logs (comprobado en CI), así que `lambda logs` no encuentra nada. `lambda invoke` sí muestra el log de cada invocación: `START`, lo que imprima la función y `REPORT` con la duración. Las invocaciones `--async` y las disparadas por SNS o EventBridge se aceptan, pero su salida no queda visible.

## Secrets Manager

```bash
awsemu secrets put db/password 's3cr3t'                         # crea el secreto
awsemu secrets put db/config '{"host": "db", "port": 5432}'     # JSON
awsemu secrets put db/password 'nuevo'                          # si existe, guarda una versión nueva
awsemu secrets put tls/key --file key.pem
awsemu secrets get db/config                                    # JSON formateado
awsemu secrets get db/config --raw                              # tal cual (para scripts)
awsemu secrets get db/password --stage AWSPREVIOUS              # versión anterior
awsemu secrets ls                                               # nombres, nunca valores
awsemu secrets info db/password                                 # metadatos y versiones
awsemu secrets rm db/password --yes                             # recuperable 7 días
awsemu secrets rm db/password --now --yes                       # sin recuperación
```

## SSM Parameter Store

```bash
awsemu ssm put /app/db/host localhost
awsemu ssm put /app/db/password s3cr3t --secure     # SecureString (se muestra como ****)
awsemu ssm put /app/hosts a,b,c --list              # StringList
awsemu ssm get /app/db/password                     # descifrado
awsemu ssm ls                                       # todos
awsemu ssm ls /app --values                         # bajo una ruta, con valores
awsemu ssm rm /app/db/host /app/db/password
```

`put` sobrescribe si ya existe (y sube la versión). Como en AWS, los nombres no pueden empezar por `aws` ni `ssm`: `/awsapp/x` también se rechaza.

## EventBridge

`events rule` crea la regla y su destino en un solo paso, con los permisos necesarios (política de la cola SQS o permiso de invocación de Lambda):

```bash
awsemu sqs create eventos-pedidos
awsemu events rule pedidos-creados --source app.pedidos --to-sqs eventos-pedidos
awsemu events put app.pedidos PedidoCreado '{"id": 42, "total": 120}'
awsemu sqs receive eventos-pedidos --delete            # el evento completo, con "detail"

awsemu events rule pedidos-grandes \
    --pattern '{"source": ["app.pedidos"], "detail": {"total": [{"numeric": [">", 100]}]}}' \
    --to-lambda avisar
awsemu events rule cada-5-min --schedule 'rate(5 minutes)' --to-sns recordatorios

awsemu events rules                    # reglas del bus default con patrón y destinos
awsemu events buses
awsemu events create-bus pedidos       # bus propio; luego --bus pedidos en rule/put/rules/rm
awsemu events rm pedidos-creados --yes # quita los destinos y borra la regla
```

## Kinesis

```bash
awsemu kinesis create clics --shards 2         # espera a que esté activo
awsemu kinesis put clics '{"pagina": "/"}' -k usuario-1
cat evento.bin | awsemu kinesis put clics --file -
awsemu kinesis read clics                      # desde el principio, todos los shards
awsemu kinesis read clics --from latest -f     # solo lo nuevo, sin parar (Ctrl+C)
awsemu kinesis read clics --json -n 0          # un JSON por registro, sin límite
awsemu kinesis ls
awsemu kinesis rm clics --yes
```

`read` muestra los datos como JSON compacto si lo son, como texto si son UTF-8, y en hexadecimal si no.

## Step Functions

```bash
# flujo.asl.json
# {"StartAt": "Saludar",
#  "States": {"Saludar": {"Type": "Pass",
#                         "Parameters": {"saludo.$": "States.Format('hola {}', $.nombre)"},
#                         "End": true}}}

awsemu sfn deploy saludo flujo.asl.json        # crea (y el rol awsemu-sfn-role) o actualiza
awsemu sfn start saludo '{"nombre": "Ana"}'    # espera y muestra la salida
awsemu sfn start saludo --raw                  # solo la salida JSON; código 1 si falla
awsemu sfn start saludo --no-wait
awsemu sfn executions saludo
awsemu sfn ls
awsemu sfn rm saludo --yes
```

Si la ejecución falla, `start` muestra el error y la causa (o los busca en el historial) y termina con código 1. La definición puede ser un fichero o JSON en línea; se valida antes de enviarla.

## Cualquier recurso por su ARN

```bash
awsemu describe arn:aws:dynamodb:us-east-1:000000000000:table/usuarios
awsemu describe arn:aws:sqs:us-east-1:000000000000:trabajos
awsemu describe arn:aws:s3:::fotos/gato.jpg
awsemu describe arn:aws:states:us-east-1:000000000000:execution:saludo:awsemu-1a2b3c
```

Funciona con ARNs de S3, SQS, DynamoDB, SNS (temas y suscripciones), Lambda, Secrets Manager, SSM, Kinesis, EventBridge (reglas y buses), Step Functions (máquinas y ejecuciones), CloudWatch Logs e IAM (roles, usuarios y políticas). La salida es JSON.

## Configuración del emulador

```bash
awsemu config show                 # contenido de ~/.aws/emulator/config.toml (o $EMULATOR_CONFIG)
awsemu config telemetry            # estado actual
awsemu config telemetry off        # [telemetry] enabled = false
awsemu config path
```

`awsemu` edita el fichero sin perder tus comentarios ni otras opciones.
