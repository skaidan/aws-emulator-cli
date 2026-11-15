# Guía de servicios

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
awsemu lambda logs api -f                      # logs de CloudWatch (/aws/lambda/api)
awsemu lambda info api
awsemu lambda ls
awsemu lambda rm api --yes
```

`invoke` termina con código 1 si la función lanza un error, para que los scripts lo detecten.

## Configuración del emulador

```bash
awsemu config show                 # contenido de ~/.aws/emulator/config.toml (o $EMULATOR_CONFIG)
awsemu config telemetry            # estado actual
awsemu config telemetry off        # [telemetry] enabled = false
awsemu config path
```

`awsemu` edita el fichero sin perder tus comentarios ni otras opciones.
