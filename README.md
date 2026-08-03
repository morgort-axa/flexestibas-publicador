# PUBLICADOR — FLEXESTIBAS

Aprobar contenido desde el teléfono. Tu PC no participa.

```
Tú produces el reel  →  encolar.py  →  git push
                                          ↓
                              GitHub Actions (cada 15 min)
                                          ↓
                    Telegram: video + caption + [✅ Aprobar]
                                          ↓
                          Martes 07:00 → te avisa y publicas
```

---

## Por qué la publicación no es 100% automática

**La Graph API de Meta no puede adjuntar audio de la biblioteca de Instagram.**
Un reel publicado por API sale con el audio embebido en el archivo, y nada más.
Los audios en tendencia solo se agregan desde la app, a mano.

Además, las cuentas Business tienen la biblioteca de música restringida por
licencias. Usar música comercial sin licencia desde una cuenta de empresa es
lo que dispara strikes de copyright.

Por eso el modo por defecto es **manual**: el sistema automatiza producción,
calendario, caption, aprobación y recordatorio — el 95% del trabajo. Publicar
te toma 40 segundos y conservas el audio en tendencia.

Si algún día el audio deja de importar, `MODO_PUBLICACION=auto` publica solo.
Es cambiar una variable.

---

## Puesta en marcha (una sola vez)

### 1. Crear el bot de Telegram
En Telegram, escribe a **@BotFather** → `/newbot` → nombre → te da un token.

Para el chat id: escríbele algo a tu bot, luego abre en el navegador
`https://api.telegram.org/bot<TU_TOKEN>/getUpdates` y busca `"chat":{"id":...}`.

### 2. Crear el repo público
Este repo debe ser **público**: Meta descarga los assets por URL, y de un repo
privado no puede. Aquí no vive nada sensible — solo videos que van a publicarse
igual y captions. **El token nunca entra al repo, va en Secrets.**

```
cd PUBLICADOR
git init && git add . && git commit -m "publicador"
git remote add origin https://github.com/morgort-axa/flexestibas-publicador.git
git push -u origin main
```

### 3. Configurar en GitHub
`Settings → Secrets and variables → Actions`

**Secrets:**

| Nombre | Qué es |
|---|---|
| `TELEGRAM_BOT_TOKEN` | El de BotFather |
| `TELEGRAM_CHAT_ID` | Tu chat id |
| `META_ACCESS_TOKEN` | Solo para modo auto |
| `IG_USER_ID` | Solo para modo auto |
| `FB_PAGE_ID` | Solo para modo auto |

**Variables:**

| Nombre | Valor |
|---|---|
| `REPO_PUBLICO_BASE` | `https://raw.githubusercontent.com/morgort-axa/flexestibas-publicador/main` |
| `MODO_PUBLICACION` | `manual` |

En modo manual solo hacen falta los dos primeros secrets.

---

## Uso diario

**Ver el calendario y qué falta:**
```
python sistema/encolar.py --listar
```

**Meter una pieza ya producida:**
```
python sistema/encolar.py --pieza 2026-08-04_el-costo-invisible \
                          --video "C:\ruta\final.mp4" \
                          --audio "nombre del audio en tendencia"
git add COLA && git commit -m "encolada" && git push
```

La fecha y la hora **no se escriben a mano**: salen de `ruta_contenido.json`,
única fuente de verdad del cronograma.

**Después:** 4 días antes el bot te manda el video con botones. Apruebas desde
donde estés. A la hora programada te llega el recordatorio con el video en
calidad original y el caption listo para copiar de un toque.

---

## Las tres barreras que bloquean una aprobación

El bot **se niega a aprobar** una pieza si detecta:

| Bloqueo | Por qué |
|---|---|
| El caption no cierra en pregunta | 32 posts, ninguno preguntaba, 4 comentarios en 6 meses |
| Hashtags de reclutamiento | `#estibadores` atrae postulantes, no empresas. El reel que los usó fue el de peor alcance del período (361 repr.) |
| `[CORCHETES]` sin resolver | Son datos reales por confirmar. Nunca se rellenan a ojo |

No son sugerencias: el botón de aprobar no funciona hasta corregirlos.

---

## Estructura

```
PUBLICADOR/
├── sistema/
│   ├── cola.py       la fuente de verdad del estado
│   ├── ciclo.py      corre en GitHub Actions cada 15 min
│   ├── telegram.py   cliente del bot
│   ├── encolar.py    puente producción → cola (corre en tu PC)
│   ├── publicar.py   modo auto, vía Graph API
│   └── meta_api.py   cliente de Meta
├── COLA/             una carpeta por pieza; el estado vive en git
└── LOG/              historial de todo lo que pasó
```

El estado en git da historial auditable gratis: qué se aprobó, cuándo y qué se
publicó queda en el log de commits.

---

## Garantías

- **Idempotente.** Nada se publica dos veces. `concurrency` impide ciclos solapados.
- **Nada sale sin tu aprobación explícita.** `aprobado: false` es el default.
- **Tras 3 fallos una pieza se bloquea** y avisa, en vez de reintentar para siempre.
- **Ventana de 48 h:** algo olvidado dos días no se publica de sorpresa.

## Sobre el antecedente de restricción

Meta atribuyó la restricción del 19 jul a "actividad automatizada". Eso fue por
usar la **API privada** (`/api/v1/feed/user/`) con sesión autenticada — scraping,
y viola los términos.

Este sistema usa la **Graph API oficial** con app registrada y token, que es el
camino documentado y permitido por Meta. Son cosas opuestas. Aun así: antes de
activar el modo auto, confirmar que el Business Manager está sin restricciones.
