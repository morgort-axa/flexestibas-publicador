"""
La cola: lectura y escritura del estado de cada pieza.

Una pieza es una carpeta en COLA/ con esta forma:

    COLA/2026-08-04_montacarguista-vs-clam/
    ├── estado.json     <- la fuente de verdad
    ├── caption.txt     <- copy listo, escrito con MORITA
    └── media/final.mp4

El estado vive en git. Eso da historial completo y auditable de que se
aprobo, cuando, y que se publico — gratis.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
COLA = RAIZ / "COLA"
LOG = RAIZ / "LOG"

ECUADOR = timezone(timedelta(hours=-5))
MAX_INTENTOS = 3
VENTANA_HORAS = 48        # no publicar algo que quedo olvidado hace dias
AVISO_DIAS_ANTES = 4      # con cuanta anticipacion se pide la aprobacion


def ahora():
    return datetime.now(ECUADOR)


def registrar(evento, **datos):
    LOG.mkdir(parents=True, exist_ok=True)
    with (LOG / "actividad.jsonl").open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {"cuando": ahora().isoformat(), "evento": evento, **datos},
                ensure_ascii=False,
            )
            + "\n"
        )


# Marcas de que una linea es CTA o contacto, no argumento. Se buscan EN CUALQUIER
# parte de la linea: los CTA rotan su redaccion y no siempre empiezan igual.
SENALES_CIERRE = (
    "flexestibas.com", "http", "www.", "enlace en la bio",
    "whatsapp", "escribenos", "cotiza en", "wa.me",
)


def cierra_en_pregunta(caption):
    """
    La pregunta debe cerrar el ARGUMENTO, no el texto crudo: los hashtags y la
    linea de CTA van despues y no cuentan. Se recorre de atras hacia adelante
    ignorandolos, hasta dar con la ultima linea de contenido real.
    """
    for linea in reversed([l.strip() for l in caption.splitlines() if l.strip()]):
        bajo = linea.lower()
        if any(s in bajo for s in SENALES_CIERRE):
            continue
        if all(p.startswith("#") for p in bajo.split()):
            continue
        return linea.endswith("?")
    return False


class Pieza:
    def __init__(self, carpeta):
        self.carpeta = carpeta
        self.ruta_estado = carpeta / "estado.json"
        with self.ruta_estado.open(encoding="utf-8") as f:
            self.d = json.load(f)

    # ------------------------------------------------------------ atajos

    @property
    def nombre(self):
        return self.carpeta.name

    @property
    def titulo(self):
        return self.d.get("titulo", self.nombre)

    @property
    def aprobado(self):
        return bool(self.d.get("aprobado"))

    @property
    def descartado(self):
        return bool(self.d.get("descartado"))

    @property
    def formato(self):
        return self.d.get("formato", "reel")

    @property
    def redes(self):
        return self.d.get("redes", ["instagram"])

    @property
    def intentos(self):
        return self.d.get("intentos", 0)

    @property
    def programado(self):
        valor = self.d.get("programado")
        if not valor:
            return None
        try:
            fecha = datetime.fromisoformat(valor)
        except ValueError:
            return None
        return fecha.replace(tzinfo=ECUADOR) if fecha.tzinfo is None else fecha

    @property
    def pendientes(self):
        publicado = self.d.get("publicado", {})
        return [r for r in self.redes if not publicado.get(r)]

    def media(self):
        rutas = []
        for rel in self.d.get("media", []):
            archivo = self.carpeta / rel
            if archivo.exists():
                rutas.append(archivo)
        return rutas

    def caption(self):
        archivo = self.carpeta / self.d.get("caption_file", "caption.txt")
        if not archivo.exists():
            return ""
        return archivo.read_text(encoding="utf-8").strip()

    # ------------------------------------------------------------ escribir

    def set(self, **campos):
        self.d.update(campos)
        self.guardar()

    def guardar(self):
        with self.ruta_estado.open("w", encoding="utf-8") as f:
            json.dump(self.d, f, ensure_ascii=False, indent=2)
            f.write("\n")

    def marcar_publicado(self, red, media_id):
        self.d.setdefault("publicado", {})[red] = {
            "id": media_id,
            "en": ahora().isoformat(),
        }
        self.d.pop("error", None)
        self.guardar()

    def marcar_fallo(self, red, error):
        self.d["intentos"] = self.intentos + 1
        self.d["error"] = f"[{red}] {error}"
        self.guardar()

    # ------------------------------------------------------------ decisiones

    def lista_para_revision(self, momento=None):
        """Se le pide aprobacion cuando falta poco y tiene todo lo necesario."""
        momento = momento or ahora()
        if self.d.get("revision_enviada") or self.aprobado or self.descartado:
            return False
        if self.programado is None:
            return False
        if self.programado - momento > timedelta(days=AVISO_DIAS_ANTES):
            return False
        # Sin material no tiene sentido pedir aprobacion.
        return bool(self.media()) and bool(self.caption())

    def lista_para_publicar(self, momento=None):
        """Devuelve (si_o_no, motivo). El motivo sirve tanto para log como para UI."""
        momento = momento or ahora()
        if self.descartado:
            return False, "descartada"
        if not self.aprobado:
            return False, "sin aprobar"
        if self.intentos >= MAX_INTENTOS:
            return False, f"bloqueada tras {MAX_INTENTOS} fallos"
        if self.programado is None:
            return False, "fecha invalida"
        if self.programado > momento:
            return False, "aun no es la hora"
        if momento - self.programado > timedelta(hours=VENTANA_HORAS):
            return False, f"vencida (mas de {VENTANA_HORAS}h tarde)"
        if not self.pendientes:
            return False, "ya publicada"
        return True, self.pendientes

    def problemas_de_calidad(self):
        """Bloqueos que NO deben llegar a produccion. Se revisan antes de aprobar."""
        fallos = []
        caption = self.caption()
        if not caption:
            fallos.append("no tiene caption")
        else:
            if "[" in caption and "]" in caption:
                fallos.append("el caption tiene [CORCHETES] sin resolver — datos por confirmar")
            if not cierra_en_pregunta(caption):
                fallos.append("el caption no cierra en pregunta (regla anti cero-comentarios)")
            prohibidos = [
                "#trabajadores", "#estibadores", "#bendecidos",
                "#personaloperativo", "#talentooperativo",
            ]
            usados = [h for h in prohibidos if h in caption.lower()]
            if usados:
                fallos.append(
                    f"hashtags de reclutamiento ({', '.join(usados)}) — contaminan la "
                    "audiencia B2B y hunden el alcance"
                )
        if not self.media():
            fallos.append("no tiene media")
        return fallos


def todas():
    if not COLA.exists():
        return []
    piezas = []
    for carpeta in sorted(COLA.iterdir()):
        if not carpeta.is_dir() or carpeta.name.startswith("_"):
            continue
        if not (carpeta / "estado.json").exists():
            continue
        piezas.append(Pieza(carpeta))
    return piezas


def buscar(nombre):
    carpeta = COLA / nombre
    if carpeta.is_dir() and (carpeta / "estado.json").exists():
        return Pieza(carpeta)
    return None


def url_publica(archivo):
    """Meta DESCARGA el archivo: necesita una URL publica de verdad."""
    base = os.environ.get("REPO_PUBLICO_BASE", "").rstrip("/")
    if not base:
        raise RuntimeError(
            "Falta REPO_PUBLICO_BASE. Ejemplo:\n"
            "  https://raw.githubusercontent.com/usuario/flexestibas-publicador/main"
        )
    relativa = str(archivo.relative_to(RAIZ)).replace(os.sep, "/")
    return f"{base}/{relativa}"
