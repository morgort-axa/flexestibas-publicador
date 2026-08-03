"""
Cliente minimo de la API de bots de Telegram.

Solo lo que el sistema necesita: mandar video con botones, leer que boton
apretaste, y confirmar el tap. Sin librerias externas mas alla de requests.

El token JAMAS se imprime ni se registra.
"""

import json

import requests

TIMEOUT = 120
# Un bot puede subir hasta 50 MB por archivo.
MAX_MB = 49


class TelegramError(RuntimeError):
    pass


class Bot:
    def __init__(self, token, chat_id):
        if not token:
            raise TelegramError("Falta TELEGRAM_BOT_TOKEN")
        if not chat_id:
            raise TelegramError("Falta TELEGRAM_CHAT_ID")
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = str(chat_id)

    def _pedir(self, metodo, archivos=None, **datos):
        r = requests.post(
            f"{self.base}/{metodo}", data=datos, files=archivos, timeout=TIMEOUT
        )
        try:
            cuerpo = r.json()
        except ValueError:
            raise TelegramError(f"Respuesta no-JSON de Telegram (HTTP {r.status_code})")
        if not cuerpo.get("ok"):
            raise TelegramError(
                f"{cuerpo.get('error_code', '')}: {cuerpo.get('description', 'sin detalle')}"
            )
        return cuerpo["result"]

    # ------------------------------------------------------------- enviar

    def mensaje(self, texto, botones=None):
        datos = {"chat_id": self.chat_id, "text": texto, "parse_mode": "HTML"}
        if botones:
            datos["reply_markup"] = json.dumps({"inline_keyboard": botones})
        return self._pedir("sendMessage", **datos)

    def video(self, ruta, texto, botones=None):
        """Manda el video para que lo veas antes de aprobar."""
        mb = ruta.stat().st_size / 1_048_576
        if mb > MAX_MB:
            # Demasiado pesado para el bot: mandamos la ficha sin el video.
            return self.mensaje(
                texto + f"\n\n⚠️ El video pesa {mb:.0f} MB y no cabe en Telegram "
                f"(limite {MAX_MB} MB). Revisalo en la carpeta antes de aprobar.",
                botones,
            )
        datos = {"chat_id": self.chat_id, "caption": texto, "parse_mode": "HTML"}
        if botones:
            datos["reply_markup"] = json.dumps({"inline_keyboard": botones})
        with ruta.open("rb") as f:
            return self._pedir("sendVideo", archivos={"video": f}, **datos)

    def foto(self, ruta, texto, botones=None):
        datos = {"chat_id": self.chat_id, "caption": texto, "parse_mode": "HTML"}
        if botones:
            datos["reply_markup"] = json.dumps({"inline_keyboard": botones})
        with ruta.open("rb") as f:
            return self._pedir("sendPhoto", archivos={"photo": f}, **datos)

    def documento(self, ruta, texto):
        """Para mandarte el video en calidad original, sin compresion de Telegram."""
        with ruta.open("rb") as f:
            return self._pedir(
                "sendDocument",
                archivos={"document": f},
                chat_id=self.chat_id,
                caption=texto,
                parse_mode="HTML",
            )

    # ------------------------------------------------------------- recibir

    def novedades(self, offset=0):
        """Lee los botones que apretaste desde la ultima revision."""
        return self._pedir(
            "getUpdates",
            offset=offset,
            timeout=0,
            allowed_updates=json.dumps(["callback_query", "message"]),
        )

    def confirmar_tap(self, callback_id, aviso=""):
        """Quita el relojito del boton en tu telefono."""
        try:
            self._pedir("answerCallbackQuery", callback_query_id=callback_id, text=aviso)
        except TelegramError:
            pass  # Un callback viejo ya expiro; no es motivo para frenar el ciclo.

    def quitar_botones(self, message_id):
        """Tras decidir, los botones ya no sirven: se retiran para no re-tocarlos."""
        try:
            self._pedir(
                "editMessageReplyMarkup",
                chat_id=self.chat_id,
                message_id=message_id,
                reply_markup=json.dumps({"inline_keyboard": []}),
            )
        except TelegramError:
            pass


def botones_revision(slug):
    return [
        [
            {"text": "✅ Aprobar", "callback_data": f"ok:{slug}"},
            {"text": "❌ Descartar", "callback_data": f"no:{slug}"},
        ],
        [{"text": "⏸ Posponer una semana", "callback_data": f"mv:{slug}"}],
    ]
