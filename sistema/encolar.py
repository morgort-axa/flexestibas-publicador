"""
Encolar — el puente entre la produccion y el bot.

Se corre EN TU PC, cuando ya tienes el video de una pieza listo.
Toma el guion y el caption del calendario, los junta con tu video, y deja
la entrada en COLA/ para que el bot te pida aprobacion desde el telefono.

    python encolar.py --listar
    python encolar.py --pieza 2026-08-04_costo-invisible --video "C:\\ruta\\final.mp4"

La fecha y la hora NO se escriben a mano: salen del calendario
(ruta_contenido.json), que es la unica fuente de verdad del cronograma.
"""

import argparse
import importlib.util
import json
import shutil
import sys
import zlib
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cola

# El calendario vive en el proyecto privado; la cola, en el repo publico.
PROYECTO = cola.RAIZ.parent
RUTA_JSON = PROYECTO / "PRODUCCION" / "_sistema" / "ruta_contenido.json"
MOTOR = PROYECTO / "PRODUCCION" / "_sistema" / "preparar_material.py"


def cargar_calendario():
    """Reusa la funcion calendario() del motor: una sola logica de fechas."""
    if not RUTA_JSON.exists():
        raise SystemExit(f"No encuentro el calendario: {RUTA_JSON}")
    if not MOTOR.exists():
        raise SystemExit(f"No encuentro el motor: {MOTOR}")

    spec = importlib.util.spec_from_file_location("preparar_material", MOTOR)
    motor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(motor)

    cfg = json.loads(RUTA_JSON.read_text(encoding="utf-8"))
    hoy = date.today()
    agenda = motor.calendario(cfg, hoy - timedelta(days=30), hoy + timedelta(days=90))
    return cfg, agenda


def nombre_de(pieza):
    return f"{pieza['fecha'].isoformat()}_{pieza['slug']}"


CAPTIONS = PROYECTO / "PRODUCCION" / "_sistema" / "captions.json"


def caption_de(pieza, cfg):
    """
    Prefiere el caption escrito con MORITA. Si no existe para este slug, cae
    al armado mecanico del motor (hook+tension+respuesta+cta), que sirve como
    red de seguridad pero repite el guion del video — por eso rinde menos.
    """
    tags = " ".join(cfg.get("hashtags_fijos", []))
    if pieza.get("rotativo"):
        tags += " " + pieza["rotativo"]

    # El CTA rota: la misma linea 22 veces le dice a Instagram "contenido repetitivo".
    # crc32 y no hash(): hash() cambia entre ejecuciones y el CTA bailaria en cada corrida.
    ctas = cfg.get("cta_web") or ["Mas en flexestibas.com — enlace en la bio."]
    cta = ctas[zlib.crc32(pieza["slug"].encode()) % len(ctas)]
    cierre = f"\n\n{cta}\n\n{tags}\n"

    if CAPTIONS.exists():
        escritos = json.loads(CAPTIONS.read_text(encoding="utf-8"))
        cuerpo = escritos.get(pieza["slug"])
        if cuerpo:
            return cuerpo.rstrip() + cierre
        print(f"  AVISO: '{pieza['slug']}' no tiene caption en captions.json.")
        print("         Se usa el armado mecanico — revisalo antes de aprobar.")

    return (
        f"{pieza['hook']}\n\n{pieza['tension']}\n\n{pieza['respuesta']}\n\n"
        f"{pieza['cta']}" + cierre
    )


def listar(agenda):
    print(f"{'PIEZA':<48} {'CUANDO':<20} ESTADO")
    print("-" * 88)
    for p in agenda:
        nombre = nombre_de(p)
        existente = cola.buscar(nombre)
        if existente is None:
            estado = "sin encolar"
        elif existente.d.get("publicado"):
            estado = "publicada"
        elif existente.aprobado:
            estado = "aprobada"
        elif existente.descartado:
            estado = "descartada"
        elif existente.d.get("revision_enviada"):
            estado = "esperando tu OK"
        else:
            estado = "en cola"
        cuando = f"{p['dia'][:3]} {p['fecha'].isoformat()} {p['hora']}"
        print(f"{nombre:<48} {cuando:<20} {estado}")


def encolar(nombre, video, cfg, agenda, audio=None, redes=None, forzar=False):
    pieza = next((p for p in agenda if nombre_de(p) == nombre), None)
    if pieza is None:
        raise SystemExit(
            f"'{nombre}' no esta en el calendario.\n"
            "Corre --listar para ver los nombres exactos."
        )

    origen = Path(video)
    if not origen.exists():
        raise SystemExit(f"No encuentro el video: {origen}")

    destino = cola.COLA / nombre
    if destino.exists() and not forzar:
        raise SystemExit(
            f"'{nombre}' ya esta en la cola. Usa --forzar para reemplazar el video."
        )

    (destino / "media").mkdir(parents=True, exist_ok=True)
    archivo = destino / "media" / f"final{origen.suffix.lower()}"
    shutil.copy2(origen, archivo)

    mb = archivo.stat().st_size / 1_048_576
    if mb > 95:
        print(f"  AVISO: el video pesa {mb:.0f} MB. GitHub corta en 100 MB.")

    (destino / "caption.txt").write_text(caption_de(pieza, cfg), encoding="utf-8")

    programado = datetime.combine(
        pieza["fecha"], datetime.strptime(pieza["hora"], "%H:%M").time()
    ).replace(tzinfo=cola.ECUADOR)

    estado = {
        "slug": pieza["slug"],
        "titulo": pieza["titulo"],
        "pilar": pieza["pilar"],
        "serie": pieza.get("serie", ""),
        "programado": programado.isoformat(),
        "formato": pieza["formato"],
        "redes": redes or ["instagram", "facebook"],
        "media": [f"media/{archivo.name}"],
        "caption_file": "caption.txt",
        "audio_sugerido": audio or "",
        "aprobado": False,
        "descartado": False,
        "revision_enviada": False,
        "recordatorio_enviado": False,
        "publicado": {},
        "intentos": 0,
    }
    with (destino / "estado.json").open("w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Encolada: {nombre}")
    print(f"  Publica: {programado.strftime('%A %d/%m a las %H:%M')}")
    print(f"  Video:   {archivo.name} ({mb:.1f} MB)")

    avisos = cola.Pieza(destino).problemas_de_calidad()
    if avisos:
        print("  Revisar antes de aprobar:")
        for a in avisos:
            print(f"    - {a}")

    print("\nSubelo al repo publico para que el bot te lo mande:")
    print("  git add COLA && git commit -m 'encolada: {}' && git push".format(nombre))


def main():
    ap = argparse.ArgumentParser(description="Mete una pieza producida a la cola")
    ap.add_argument("--listar", action="store_true", help="Ver el calendario y su estado")
    ap.add_argument("--pieza", help="Nombre exacto (ver --listar)")
    ap.add_argument("--video", help="Ruta al video final")
    ap.add_argument("--audio", help="Audio en tendencia elegido, para el recordatorio")
    ap.add_argument("--solo-ig", action="store_true", help="Publicar solo en Instagram")
    ap.add_argument("--forzar", action="store_true", help="Reemplazar si ya existe")
    args = ap.parse_args()

    cfg, agenda = cargar_calendario()

    if args.listar or not args.pieza:
        listar(agenda)
        if not args.pieza:
            print("\nPara encolar:  --pieza <nombre> --video <ruta>")
        return 0

    if not args.video:
        raise SystemExit("Falta --video")

    encolar(
        args.pieza, args.video, cfg, agenda,
        audio=args.audio,
        redes=["instagram"] if args.solo_ig else None,
        forzar=args.forzar,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
