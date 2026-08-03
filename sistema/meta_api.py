"""
Cliente de Meta Graph API para publicar en Instagram y Facebook.

Sin magia: cada funcion hace una llamada documentada de la Graph API y
devuelve el id publicado. Si algo falla, levanta MetaError con el mensaje
que devolvio Meta, nunca un fallo silencioso.

El token JAMAS se imprime ni se registra.
"""

import time

import requests

VERSION = "v23.0"
BASE = f"https://graph.facebook.com/{VERSION}"
BASE_VIDEO = f"https://graph-video.facebook.com/{VERSION}"

TIMEOUT = 60
# Un reel tarda en procesarse del lado de Meta. Sondeamos hasta 8 minutos.
POLL_INTERVALO = 10
POLL_MAX = 48


class MetaError(RuntimeError):
    """Error devuelto por la Graph API, ya legible."""


def _pedir(metodo, url, token, **params):
    params["access_token"] = token
    r = requests.request(metodo, url, data=params, timeout=TIMEOUT)
    try:
        cuerpo = r.json()
    except ValueError:
        raise MetaError(f"Respuesta no-JSON de Meta (HTTP {r.status_code})")

    if "error" in cuerpo:
        e = cuerpo["error"]
        raise MetaError(
            f"{e.get('type', 'Error')} {e.get('code', '')}: {e.get('message', '')}"
            + (f" | {e['error_user_msg']}" if e.get("error_user_msg") else "")
        )
    if r.status_code >= 400:
        raise MetaError(f"HTTP {r.status_code} de Meta")
    return cuerpo


# ---------------------------------------------------------------- Instagram


def _ig_esperar_contenedor(container_id, token):
    """Un contenedor de video no se puede publicar hasta que Meta lo termina."""
    for _ in range(POLL_MAX):
        estado = _pedir(
            "GET", f"{BASE}/{container_id}", token, fields="status_code,status"
        )
        codigo = estado.get("status_code")
        if codigo == "FINISHED":
            return
        if codigo in ("ERROR", "EXPIRED"):
            raise MetaError(
                f"Contenedor {codigo}: {estado.get('status', 'sin detalle')}"
            )
        time.sleep(POLL_INTERVALO)
    raise MetaError(
        f"El contenedor sigue procesando tras {POLL_MAX * POLL_INTERVALO}s. "
        "No se publico para no dejarlo a medias; se reintenta en la proxima corrida."
    )


def ig_publicar_reel(ig_user_id, token, video_url, caption, portada_url=None):
    params = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": "true",
    }
    if portada_url:
        params["cover_url"] = portada_url

    contenedor = _pedir("POST", f"{BASE}/{ig_user_id}/media", token, **params)["id"]
    _ig_esperar_contenedor(contenedor, token)
    return _pedir(
        "POST", f"{BASE}/{ig_user_id}/media_publish", token, creation_id=contenedor
    )["id"]


def ig_publicar_imagen(ig_user_id, token, image_url, caption):
    contenedor = _pedir(
        "POST", f"{BASE}/{ig_user_id}/media", token, image_url=image_url, caption=caption
    )["id"]
    _ig_esperar_contenedor(contenedor, token)
    return _pedir(
        "POST", f"{BASE}/{ig_user_id}/media_publish", token, creation_id=contenedor
    )["id"]


def ig_publicar_carrusel(ig_user_id, token, image_urls, caption):
    if not 2 <= len(image_urls) <= 10:
        raise MetaError(
            f"Un carrusel de Instagram lleva entre 2 y 10 imagenes; llegaron {len(image_urls)}"
        )

    hijos = []
    for url in image_urls:
        hijos.append(
            _pedir(
                "POST",
                f"{BASE}/{ig_user_id}/media",
                token,
                image_url=url,
                is_carousel_item="true",
            )["id"]
        )

    contenedor = _pedir(
        "POST",
        f"{BASE}/{ig_user_id}/media",
        token,
        media_type="CAROUSEL",
        children=",".join(hijos),
        caption=caption,
    )["id"]
    _ig_esperar_contenedor(contenedor, token)
    return _pedir(
        "POST", f"{BASE}/{ig_user_id}/media_publish", token, creation_id=contenedor
    )["id"]


def ig_cuota_restante(ig_user_id, token):
    """Instagram permite 50 publicaciones por cada 24h. Devuelve cuantas quedan."""
    try:
        r = _pedir(
            "GET", f"{BASE}/{ig_user_id}/content_publishing_limit", token,
            fields="quota_usage,config",
        )
        datos = r.get("data", [{}])[0]
        usadas = datos.get("quota_usage", 0)
        total = datos.get("config", {}).get("quota_total", 50)
        return total - usadas
    except MetaError:
        # Si el endpoint de cuota falla no bloqueamos la publicacion.
        return None


# ---------------------------------------------------------------- Facebook


def fb_publicar_foto(page_id, token, image_url, caption):
    return _pedir(
        "POST", f"{BASE}/{page_id}/photos", token,
        url=image_url, caption=caption, published="true",
    )["id"]


def fb_publicar_video(page_id, token, video_url, descripcion):
    return _pedir(
        "POST", f"{BASE_VIDEO}/{page_id}/videos", token,
        file_url=video_url, description=descripcion,
    )["id"]


def fb_publicar_reel(page_id, token, video_url, descripcion):
    """Reel de pagina: tres fases (start, upload por URL, finish)."""
    inicio = _pedir(
        "POST", f"{BASE}/{page_id}/video_reels", token, upload_phase="start"
    )
    video_id = inicio["video_id"]

    subida = requests.post(
        inicio["upload_url"],
        headers={"Authorization": f"OAuth {token}", "file_url": video_url},
        timeout=TIMEOUT,
    )
    if subida.status_code >= 400:
        raise MetaError(f"Fallo la subida del reel a Facebook (HTTP {subida.status_code})")

    _pedir(
        "POST", f"{BASE}/{page_id}/video_reels", token,
        video_id=video_id, upload_phase="finish",
        video_state="PUBLISHED", description=descripcion,
    )
    return video_id


def verificar_credenciales(token, ig_user_id=None, page_id=None):
    """Comprueba que el token sirve y alcanza las cuentas. Devuelve lista de problemas."""
    problemas = []
    try:
        _pedir("GET", f"{BASE}/me", token, fields="id,name")
    except MetaError as e:
        return [f"El token no es valido: {e}"]

    if ig_user_id:
        try:
            _pedir("GET", f"{BASE}/{ig_user_id}", token, fields="username")
        except MetaError as e:
            problemas.append(f"No alcanzo la cuenta de Instagram {ig_user_id}: {e}")
    if page_id:
        try:
            _pedir("GET", f"{BASE}/{page_id}", token, fields="name")
        except MetaError as e:
            problemas.append(f"No alcanzo la pagina de Facebook {page_id}: {e}")
    return problemas
