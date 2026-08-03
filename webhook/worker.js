/**
 * Receptor instantaneo de Telegram — FLEXESTIBAS
 *
 * Vive en Cloudflare Workers. Su unico trabajo es que el boton responda
 * al instante: cuando tocas Aprobar, este codigo contesta en milisegundos
 * y RECIEN DESPUES le avisa a GitHub que guarde el estado.
 *
 * Sin esto, el bot preguntaba cada 5 minutos si habias respondido, y el
 * boton se quedaba con el reloj girando. Se sentia roto aunque funcionara.
 *
 * Variables que necesita (se configuran en el panel de Cloudflare):
 *   TELEGRAM_BOT_TOKEN  para contestarle a Telegram
 *   GITHUB_TOKEN        para disparar el guardado en el repo
 *   WEBHOOK_SECRET      para que nadie mas pueda mandar ordenes falsas
 */

const REPO = "morgort-axa/flexestibas-publicador";

const RESPUESTA = {
  ok: "Aprobada ✅",
  no: "Descartada",
  mv: "Pospuesta una semana",
};

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "POST") {
      return new Response("Receptor de FLEXESTIBAS activo", { status: 200 });
    }

    // Telegram manda este header en cada aviso. Si no coincide, no es Telegram.
    const firma = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
    if (firma !== env.WEBHOOK_SECRET) {
      return new Response("no autorizado", { status: 401 });
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("ok", { status: 200 });
    }

    const cb = update.callback_query;
    if (!cb) {
      // Mensajes normales: no hacemos nada, pero confirmamos recepcion.
      return new Response("ok", { status: 200 });
    }

    const datos = cb.data || "";
    const sep = datos.indexOf(":");
    const accion = sep > 0 ? datos.slice(0, sep) : "";
    const pieza = sep > 0 ? datos.slice(sep + 1) : "";

    // 1. Contestar YA. Esto es lo que quita el reloj del boton.
    ctx.waitUntil(
      tg(env, "answerCallbackQuery", {
        callback_query_id: cb.id,
        text: RESPUESTA[accion] || "Recibido",
      })
    );

    // Solo estas tres acciones y nombres de pieza sin caracteres raros.
    // GitHub vuelve a validarlo del otro lado: si algo se cuela aqui,
    // alla se rechaza igual.
    const ACCIONES = ["ok", "no", "mv"];
    if (!ACCIONES.includes(accion) || !/^[A-Za-z0-9._-]+$/.test(pieza)) {
      return new Response("ok", { status: 200 });
    }

    // 2. Quitar los botones para que no se toque dos veces.
    ctx.waitUntil(
      tg(env, "editMessageReplyMarkup", {
        chat_id: cb.message.chat.id,
        message_id: cb.message.message_id,
        reply_markup: JSON.stringify({ inline_keyboard: [] }),
      })
    );

    // 3. Avisar a GitHub que aplique y guarde la decision.
    ctx.waitUntil(avisarGitHub(env, accion, pieza));

    return new Response("ok", { status: 200 });
  },
};

async function tg(env, metodo, cuerpo) {
  return fetch(
    `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${metodo}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cuerpo),
    }
  );
}

async function avisarGitHub(env, accion, pieza) {
  const r = await fetch(
    `https://api.github.com/repos/${REPO}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `token ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "flexestibas-webhook",
      },
      body: JSON.stringify({
        event_type: "decision-telegram",
        client_payload: { accion, pieza },
      }),
    }
  );
  if (!r.ok) {
    // El usuario ya vio su confirmacion; esto solo queda en los logs.
    console.log("fallo el dispatch a GitHub:", r.status, await r.text());
  }
}
