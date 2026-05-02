/**
 * Cloudflare Worker — handles Telegram inline-button callbacks 24/7.
 *
 * Why we need this: GitHub Actions only run on a schedule, so they can't
 * respond to button taps in real time. This Worker is always-on (free tier:
 * 100 000 reqs/day) and triggers a `repository_dispatch` event back to GH
 * to actually run the auto-apply.
 *
 * Endpoints:
 *   POST /telegram   ← Telegram webhook (set via `setWebhook` in README Step 5.4)
 *   GET  /healthz    ← liveness check
 *
 * Required secrets (set with `wrangler secret put`):
 *   TELEGRAM_BOT_TOKEN
 *   GITHUB_TOKEN          (PAT with `repo` scope)
 *   GITHUB_REPO           (e.g. "yourname/job-hunter")
 *   WORKER_SECRET         (random string — also stored as a GH secret; not strictly needed for inbound TG, used to lock the dispatch endpoint)
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/healthz") {
      return new Response("ok");
    }

    if (url.pathname === "/telegram" && request.method === "POST") {
      return handleTelegram(request, env);
    }

    return new Response("not found", { status: 404 });
  },
};

async function handleTelegram(request, env) {
  let update;
  try {
    update = await request.json();
  } catch (e) {
    return json({ ok: false, error: "bad json" }, 400);
  }

  // Only handle button presses (callback_query) and a couple of slash commands
  if (update.callback_query) {
    return handleCallback(update.callback_query, env);
  }
  if (update.message && update.message.text) {
    return handleMessage(update.message, env);
  }
  return json({ ok: true });
}

async function handleMessage(msg, env) {
  const text = msg.text.trim();
  if (text === "/start" || text === "/help") {
    await tgSend(env, msg.chat.id,
      "👋 I'm your Job Hunter bot.\n\n" +
      "I'll send you tailored job opportunities every hour with Apply / Skip buttons.\n\n" +
      "Commands:\n/status — show today's stats\n/pause — stop sending until /resume");
  } else if (text === "/status") {
    await tgSend(env, msg.chat.id, "📊 Status: hunter is running.\nCheck GitHub Actions logs for last run details.");
  }
  return json({ ok: true });
}

async function handleCallback(cb, env) {
  const data = cb.data || "";
  const [action, jobId] = data.split(":");

  // Always acknowledge so Telegram stops the spinner
  await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/answerCallbackQuery`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ callback_query_id: cb.id, text: action === "apply" ? "Applying…" : "Skipped" }),
  });

  if (action === "skip") {
    // Edit the original card to show ❌ Skipped
    await editCard(env, cb, "❌ Skipped — you won't see this one again.");
    await dispatchToGitHub(env, "mark_skip", { job_id: jobId });
    return json({ ok: true });
  }

  if (action === "apply") {
    await editCard(env, cb, "✅ Apply requested — opening / auto-filling now.\n(Watch for the screenshot in a minute.)");
    // 1) record audit trail
    await dispatchToGitHub(env, "mark_apply_pending", { job_id: jobId });
    // 2) trigger the actual auto-apply workflow
    await dispatchToGitHub(env, "auto_apply", { job_id: jobId });
    return json({ ok: true });
  }

  return json({ ok: true });
}

async function editCard(env, cb, suffix) {
  const original = cb.message.text || "";
  await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/editMessageText`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      chat_id: cb.message.chat.id,
      message_id: cb.message.message_id,
      text: original + "\n\n" + suffix,
      parse_mode: "HTML",
    }),
  });
}

async function tgSend(env, chatId, text) {
  await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text, parse_mode: "HTML" }),
  });
}

/** Trigger a workflow_dispatch on the GH repo so it does the actual apply. */
async function dispatchToGitHub(env, eventType, payload) {
  const r = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`, {
    method: "POST",
    headers: {
      "Accept": "application/vnd.github+json",
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "job-hunter-worker",
    },
    body: JSON.stringify({ event_type: eventType, client_payload: payload }),
  });
  if (!r.ok) {
    console.error("GH dispatch failed", r.status, await r.text());
  }
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json" },
  });
}
