"""
Ciclo principal — corre en GitHub Actions cada 15 minutos.

En cada vuelta hace tres cosas, en este orden:

  1. LEE tus respuestas de Telegram (que botones apretaste) y actualiza la cola
  2. PIDE aprobacion de las piezas que se publican pronto
  3. AVISA (o publica) las piezas aprobadas cuya hora ya llego

Tu PC no participa en nada de esto.

MODO_PUBLICACION:
  manual  -> te manda el video y el caption al telefono para que publiques tu.
             Es el unico modo que permite audio en tendencia (la API de Meta
             no puede adjuntar audio de la biblioteca de Instagram).
  auto    -> publica solo por la Graph API. Sin audio de biblioteca.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cola
from telegram import Bot, TelegramError, botones_revision

OFFSET = cola.LOG / "telegram_offset.txt"


def leer_offset():
    if OFFSET.exists():
        try:
            return int(OFFSET.read_text().strip())
        except ValueError:
            pass
    return 0


def guardar_offset(valor):
    OFFSET.parent.mkdir(parents=True, exist_ok=True)
    OFFSET.write_text(str(valor))


# --------------------------------------------------------- 1. tus respuestas


def procesar_respuestas(bot):
    """Lee los botones que apretaste desde la ultima vuelta."""
    offset = leer_offset()
    try:
        novedades = bot.novedades(offset)
    except TelegramError as e:
        print(f"  No se pudo leer Telegram: {e}")
        return 0

    procesadas = 0
    ultimo = offset

    for nov in novedades:
        ultimo = max(ultimo, nov["update_id"] + 1)
        cb = nov.get("callback_query")
        if not cb:
            continue

        datos = cb.get("data", "")
        if ":" not in datos:
            bot.confirmar_tap(cb["id"])
            continue

        accion, nombre = datos.split(":", 1)
        pieza = cola.buscar(nombre)
        if pieza is None:
            bot.confirmar_tap(cb["id"], "Esa pieza ya no esta en la cola")
            continue

        if accion == "ok":
            fallos = pieza.problemas_de_calidad()
            if fallos:
                # No se aprueba algo que va a fallar o a hacer dano.
                bot.confirmar_tap(cb["id"], "Tiene problemas — mira el mensaje")
                bot.mensaje(
                    f"⚠️ <b>No pude aprobar {pieza.titulo}</b>\n\n"
                    + "\n".join(f"• {f}" for f in fallos)
                    + "\n\nCorrige y vuelvo a preguntarte."
                )
                pieza.set(revision_enviada=False)
                cola.registrar("aprobacion_rechazada", pieza=pieza.nombre, fallos=fallos)
            else:
                pieza.set(aprobado=True, descartado=False)
                bot.confirmar_tap(cb["id"], "Aprobada ✅")
                bot.quitar_botones(cb["message"]["message_id"])
                cuando = pieza.programado.strftime("%A %d/%m a las %H:%M")
                bot.mensaje(f"✅ <b>{pieza.titulo}</b>\nQueda lista para el {cuando}.")
                cola.registrar("aprobada", pieza=pieza.nombre)
            procesadas += 1

        elif accion == "no":
            pieza.set(descartado=True, aprobado=False)
            bot.confirmar_tap(cb["id"], "Descartada")
            bot.quitar_botones(cb["message"]["message_id"])
            cola.registrar("descartada", pieza=pieza.nombre)
            procesadas += 1

        elif accion == "mv":
            programado = pieza.programado
            if programado:
                nueva = programado + cola.timedelta(days=7)
                pieza.set(
                    programado=nueva.isoformat(),
                    revision_enviada=False,
                    recordatorio_enviado=False,
                )
                bot.confirmar_tap(cb["id"], "Pospuesta una semana")
                bot.quitar_botones(cb["message"]["message_id"])
                bot.mensaje(
                    f"⏸ <b>{pieza.titulo}</b>\nPasa al {nueva.strftime('%A %d/%m %H:%M')}."
                )
                cola.registrar("pospuesta", pieza=pieza.nombre, nueva=nueva.isoformat())
            procesadas += 1

    guardar_offset(ultimo)
    return procesadas


def aplicar_decision(bot, accion, nombre):
    """
    Aplica una decision que llego por webhook (el Worker ya te contesto).

    El Worker responde el boton al instante y dispara esto para que la
    decision quede guardada en git. Aqui NO se contesta el callback: eso
    ya ocurrio hace segundos.
    """
    pieza = cola.buscar(nombre)
    if pieza is None:
        print(f"  '{nombre}' no esta en la cola")
        return 0

    if accion == "ok":
        fallos = pieza.problemas_de_calidad()
        if fallos:
            pieza.set(revision_enviada=False)
            bot.mensaje(
                f"⚠️ <b>No pude aprobar {pieza.titulo}</b>\n\n"
                + "\n".join(f"• {f}" for f in fallos)
                + "\n\nCorrige y vuelvo a preguntarte."
            )
            cola.registrar("aprobacion_rechazada", pieza=nombre, fallos=fallos)
            print(f"  {nombre}: rechazada por calidad -> {fallos}")
            return 1
        pieza.set(aprobado=True, descartado=False)
        cuando = pieza.programado.strftime("%A %d/%m a las %H:%M")
        bot.mensaje(f"✅ <b>{pieza.titulo}</b>\nQueda lista para el {cuando}.")
        cola.registrar("aprobada", pieza=nombre)
        print(f"  {nombre}: APROBADA")

    elif accion == "no":
        pieza.set(descartado=True, aprobado=False)
        bot.mensaje(f"❌ <b>{pieza.titulo}</b>\nDescartada.")
        cola.registrar("descartada", pieza=nombre)
        print(f"  {nombre}: descartada")

    elif accion == "mv":
        programado = pieza.programado
        if programado:
            nueva = programado + cola.timedelta(days=7)
            pieza.set(programado=nueva.isoformat(),
                      revision_enviada=False, recordatorio_enviado=False)
            bot.mensaje(
                f"⏸ <b>{pieza.titulo}</b>\nPasa al {nueva.strftime('%A %d/%m %H:%M')}."
            )
            cola.registrar("pospuesta", pieza=nombre, nueva=nueva.isoformat())
            print(f"  {nombre}: pospuesta a {nueva.date()}")
    else:
        print(f"  accion desconocida: {accion}")
        return 0
    return 1


# --------------------------------------------------------- 2. pedir aprobacion


def ficha(pieza):
    programado = pieza.programado
    cuando = programado.strftime("%A %d/%m a las %H:%M") if programado else "sin fecha"
    audio = pieza.d.get("audio_sugerido")
    lineas = [
        f"🎬 <b>{pieza.titulo}</b>",
        f"📅 {cuando}  ·  {pieza.formato}  ·  {' + '.join(pieza.redes)}",
    ]
    if audio:
        lineas.append(f"🎵 Audio sugerido: {audio}")
    avisos = pieza.problemas_de_calidad()
    if avisos:
        lineas.append("\n⚠️ " + "\n⚠️ ".join(avisos))
    lineas.append("\n— — —\n")
    caption = pieza.caption()
    lineas.append(caption[:700] + ("…" if len(caption) > 700 else ""))
    return "\n".join(lineas)


def pedir_aprobaciones(bot):
    enviadas = 0
    for pieza in cola.todas():
        if not pieza.lista_para_revision():
            continue
        medias = pieza.media()
        texto = ficha(pieza)
        botones = botones_revision(pieza.nombre)
        try:
            principal = medias[0]
            if principal.suffix.lower() in (".mp4", ".mov"):
                bot.video(principal, texto, botones)
            else:
                bot.foto(principal, texto, botones)
            pieza.set(revision_enviada=True)
            cola.registrar("revision_enviada", pieza=pieza.nombre)
            enviadas += 1
            print(f"  Enviada a revision: {pieza.nombre}")
        except TelegramError as e:
            print(f"  No se pudo enviar {pieza.nombre}: {e}")
    return enviadas


# --------------------------------------------------------- 3. publicar / avisar


def avisar_publicacion(bot, pieza):
    """Modo manual: te mando todo listo para que publiques con audio en tendencia."""
    audio = pieza.d.get("audio_sugerido", "— elige uno en tendencia al abrir la app")
    bot.mensaje(
        f"🔔 <b>TOCA PUBLICAR</b>\n\n"
        f"🎬 {pieza.titulo}\n"
        f"📱 {' + '.join(pieza.redes)}\n"
        f"🎵 Audio: {audio}\n\n"
        f"Te mando el video y el caption abajo."
    )
    medias = pieza.media()
    if medias:
        try:
            # Como documento: Telegram no lo recomprime y llega en calidad original.
            bot.documento(medias[0], "Video en calidad original")
        except TelegramError as e:
            print(f"  No se pudo mandar el video: {e}")
    # En bloque de codigo para que un toque lo copie entero.
    bot.mensaje(
        "👇 <b>Caption — tocalo para copiarlo</b>\n\n"
        f"<code>{escapar(pieza.caption())}</code>"
    )
    pieza.set(recordatorio_enviado=True)
    cola.registrar("recordatorio_enviado", pieza=pieza.nombre)


def escapar(texto):
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def atender_publicaciones(bot, modo):
    hechas = 0
    for pieza in cola.todas():
        listo, motivo = pieza.lista_para_publicar()
        if not listo:
            continue

        if modo == "manual":
            if pieza.d.get("recordatorio_enviado"):
                continue
            avisar_publicacion(bot, pieza)
            hechas += 1
            print(f"  Aviso de publicacion: {pieza.nombre}")
        else:
            from publicar import publicar_pieza

            resultado = publicar_pieza(pieza)
            for red, ok, detalle in resultado:
                if ok:
                    bot.mensaje(f"✅ Publicada en {red}\n<b>{pieza.titulo}</b>")
                    hechas += 1
                else:
                    bot.mensaje(
                        f"❌ Fallo en {red}\n<b>{pieza.titulo}</b>\n\n{detalle}"
                    )
    return hechas


# --------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description="Ciclo de contenido FLEXESTIBAS")
    ap.add_argument("--accion", help="Decision que llego por webhook: ok | no | mv")
    ap.add_argument("--pieza", help="Nombre de la pieza a la que aplica")
    args = ap.parse_args()

    modo = os.environ.get("MODO_PUBLICACION", "manual").lower()
    if modo not in ("manual", "auto"):
        print(f"MODO_PUBLICACION invalido: {modo}")
        return 1

    try:
        bot = Bot(
            os.environ.get("TELEGRAM_BOT_TOKEN"),
            os.environ.get("TELEGRAM_CHAT_ID"),
        )
    except TelegramError as e:
        print(f"ERROR: {e}")
        return 1

    print(f"Ciclo — {cola.ahora().strftime('%Y-%m-%d %H:%M')} Ecuador · modo {modo}")

    # Llegada por webhook: aplicar la decision y salir. No se toca el resto
    # para que el guardado sea lo mas rapido posible.
    if args.accion and args.pieza:
        print(f"  webhook: {args.accion} -> {args.pieza}")
        aplicar_decision(bot, args.accion, args.pieza)
        return 0

    # Con el webhook activo, getUpdates queda vacio (Telegram no permite
    # las dos vias a la vez). Se conserva como respaldo si el webhook cae.
    if not os.environ.get("WEBHOOK_ACTIVO"):
        respuestas = procesar_respuestas(bot)
        print(f"  {respuestas} respuesta(s) tuya(s) procesada(s)")

    enviadas = pedir_aprobaciones(bot)
    print(f"  {enviadas} pieza(s) enviada(s) a revision")

    atendidas = atender_publicaciones(bot, modo)
    print(f"  {atendidas} publicacion(es) atendida(s)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
