/**
 * Cloudflare Worker — API de contacto para IngePresupuestos.
 *
 * Recibe POST JSON desde la app de escritorio y reenvía el mensaje
 * al correo del desarrollador vía Resend.com.
 *
 * Variables de entorno (configurar en Cloudflare Dashboard → Worker → Settings → Variables):
 *   RESEND_API_KEY  — API key de resend.com (sk_...)
 *   NOTIFY_EMAIL    — email destino (ej. ing.sumari@gmail.com)
 *
 * Ruta: https://ingepresupuestos.com/api/contacto  (POST)
 *
 * Deploy:
 *   1. Cloudflare Dashboard → Workers & Pages → Create → "contacto-ingepresupuestos"
 *   2. Pegar este código en el editor
 *   3. Agregar variables de entorno (RESEND_API_KEY, NOTIFY_EMAIL)
 *   4. Workers → Triggers → Custom Domains → ingepresupuestos.com/api/*
 *      (o agregar Route en el dominio: ingepresupuestos.com/api/* → worker)
 */

export default {
  async fetch(request, env) {
    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
        },
      });
    }

    if (request.method !== "POST") {
      return new Response(JSON.stringify({ error: "Method not allowed" }), {
        status: 405,
        headers: { "Content-Type": "application/json" },
      });
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return new Response(JSON.stringify({ error: "Invalid JSON" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    const { Nombre, Email, Tipo, Mensaje, Fecha } = body;
    if (!Mensaje) {
      return new Response(JSON.stringify({ error: "Mensaje requerido" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    // Correo del remitente. Se valida ANTES de usarlo como Reply-To: un valor
    // basura hace que Resend devuelva 422 y se pierda el mensaje entero, y
    // además el campo llega de fuera (nunca meterlo en una cabecera sin
    // comprobar). Si no es válido, el mensaje se envía igual — solo se pierde
    // la posibilidad de responder con un clic.
    const remitente = typeof Email === "string" ? Email.trim() : "";
    const remitenteOk =
      remitente.length <= 254 && /^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]{2,}$/.test(remitente);

    const emailBody = [
      `Nombre: ${Nombre || "(anónimo)"}`,
      `Correo: ${remitente || "(no indicado)"}${remitente && !remitenteOk ? "  ⚠ formato no válido" : ""}`,
      `Tipo: ${Tipo || "General"}`,
      `Fecha: ${Fecha || new Date().toISOString()}`,
      ``,
      `Mensaje:`,
      Mensaje,
    ].join("\n");

    const payload = {
      from: "IngePresupuestos <contacto@ingepresupuestos.com>",
      to: [env.NOTIFY_EMAIL],
      subject: `[IngePresupuestos] ${Tipo || "Contacto"} — ${Nombre || "Anónimo"}`,
      text: emailBody,
    };
    // Con esto, «Responder» en el cliente de correo va directo al usuario.
    if (remitenteOk) payload.reply_to = remitente;

    const resendRes = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!resendRes.ok) {
      const err = await resendRes.text();
      return new Response(JSON.stringify({ error: "Error al enviar", detail: err }), {
        status: 502,
        headers: {
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": "*",
        },
      });
    }

    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
      },
    });
  },
};
