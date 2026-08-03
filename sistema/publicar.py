"""
Publicacion por la Graph API oficial de Meta (modo auto).

Este modo NO puede adjuntar audio de la biblioteca de Instagram — es una
limitacion de la API de Meta, no del codigo. Si el audio en tendencia
importa, el modo correcto es "manual" (ver ciclo.py).

Uso directo, sin publicar nada:
    python publicar.py --simular
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests

import cola
import meta_api


def verificar_alcanzable(url):
    """Un 404 aqui da un error claro; sin esto Meta devuelve algo criptico."""
    try:
        r = requests.head(url, timeout=30, allow_redirects=True)
    except requests.RequestException as e:
        raise RuntimeError(f"No se pudo alcanzar el asset: {e}")
    if r.status_code == 404:
        raise RuntimeError(
            f"El asset no es publico: {url}\n"
            "Revisa que el repo sea PUBLICO y que el archivo este commiteado."
        )
    if r.status_code >= 400:
        raise RuntimeError(f"El asset devolvio HTTP {r.status_code}")


def urls_de(pieza):
    urls = []
    for archivo in pieza.media():
        mb = archivo.stat().st_size / 1_048_576
        if mb > 95:
            raise RuntimeError(
                f"{archivo.name} pesa {mb:.0f} MB. GitHub corta en 100 MB — comprime."
            )
        url = cola.url_publica(archivo)
        verificar_alcanzable(url)
        urls.append(url)
    if not urls:
        raise RuntimeError("La pieza no tiene media")
    return urls


def _instagram(pieza, urls, caption, ig_id, token):
    formato = pieza.formato
    if formato == "reel":
        portada = pieza.d.get("portada")
        portada_url = (
            cola.url_publica(pieza.carpeta / portada)
            if portada and (pieza.carpeta / portada).exists()
            else None
        )
        return meta_api.ig_publicar_reel(ig_id, token, urls[0], caption, portada_url)
    if formato == "carrusel":
        return meta_api.ig_publicar_carrusel(ig_id, token, urls, caption)
    if formato in ("imagen", "post"):
        return meta_api.ig_publicar_imagen(ig_id, token, urls[0], caption)
    raise RuntimeError(f"Formato desconocido para Instagram: {formato}")


def _facebook(pieza, urls, caption, page_id, token):
    formato = pieza.formato
    if formato == "reel":
        return meta_api.fb_publicar_reel(page_id, token, urls[0], caption)
    if formato == "video":
        return meta_api.fb_publicar_video(page_id, token, urls[0], caption)
    return meta_api.fb_publicar_foto(page_id, token, urls[0], caption)


def publicar_pieza(pieza):
    """Publica en las redes pendientes. Devuelve [(red, ok, detalle), ...]."""
    token = os.environ.get("META_ACCESS_TOKEN", "")
    ig_id = os.environ.get("IG_USER_ID", "")
    page_id = os.environ.get("FB_PAGE_ID", "")

    fallos = pieza.problemas_de_calidad()
    if fallos:
        return [("validacion", False, " · ".join(fallos))]

    try:
        caption = pieza.caption()
        urls = urls_de(pieza)
    except RuntimeError as e:
        pieza.marcar_fallo("preparacion", str(e))
        return [("preparacion", False, str(e))]

    resultados = []
    for red in pieza.pendientes:
        try:
            if red == "instagram":
                if not ig_id:
                    raise RuntimeError("Falta IG_USER_ID")
                media_id = _instagram(pieza, urls, caption, ig_id, token)
            elif red == "facebook":
                if not page_id:
                    raise RuntimeError("Falta FB_PAGE_ID")
                media_id = _facebook(pieza, urls, caption, page_id, token)
            else:
                raise RuntimeError(f"Red no soportada: {red}")

            pieza.marcar_publicado(red, media_id)
            cola.registrar("publicada", pieza=pieza.nombre, red=red, media_id=media_id)
            resultados.append((red, True, media_id))

        except (meta_api.MetaError, RuntimeError) as e:
            pieza.marcar_fallo(red, str(e))
            cola.registrar(
                "fallo", pieza=pieza.nombre, red=red, error=str(e),
                intento=pieza.intentos,
            )
            resultados.append((red, False, str(e)))

    return resultados


def main():
    ap = argparse.ArgumentParser(description="Publica la cola aprobada de FLEXESTIBAS")
    ap.add_argument("--simular", action="store_true",
                    help="Muestra que publicaria, sin publicar nada")
    args = ap.parse_args()

    token = os.environ.get("META_ACCESS_TOKEN", "")
    ig_id = os.environ.get("IG_USER_ID", "")
    page_id = os.environ.get("FB_PAGE_ID", "")

    if not args.simular:
        if not token:
            print("ERROR: falta META_ACCESS_TOKEN")
            return 1
        problemas = meta_api.verificar_credenciales(token, ig_id, page_id)
        if problemas:
            for p in problemas:
                print(f"ERROR de credenciales: {p}")
            return 1
        restante = meta_api.ig_cuota_restante(ig_id, token) if ig_id else None
        if restante is not None:
            print(f"Cuota de Instagram: quedan {restante} publicaciones hoy")
            if restante <= 0:
                return 0

    print(f"Cola — {cola.ahora().strftime('%Y-%m-%d %H:%M')} Ecuador")
    total = 0
    for pieza in cola.todas():
        listo, motivo = pieza.lista_para_publicar()
        if not listo:
            print(f"  - {pieza.nombre}: {motivo}")
            continue
        if args.simular:
            print(f"  > {pieza.nombre}: publicaria en {', '.join(motivo)}")
            for u in urls_de(pieza):
                print(f"      {u}")
            continue
        for red, ok, detalle in publicar_pieza(pieza):
            print(f"  {'OK' if ok else 'ERROR'} {red}: {detalle}")
            total += 1 if ok else 0

    print(f"Listo. {total} publicacion(es).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
