/**
 * Status pill (top right): is the API key working and the index loaded?
 */
import { fetchHealth } from "./api.js";
import { $ } from "./dom.js";

/** Refresh the status pill, brand subtitle and pipeline step 5 from /api/health. */
export async function checkHealth() {
  const box = $("#status");
  const text = $(".status-text", box);
  try {
    const health = await fetchHealth();
    box.classList.toggle("ok", health.ready);
    box.classList.toggle("bad", !health.ready);
    if (health.ready) {
      text.textContent = `${health.chat_model} \u00b7 ${health.chunks_indexed} chunks`;
    } else {
      text.textContent = health.llm.reachable ? "Model not available" : "OpenAI key / network issue";
    }
    box.title = health.ready ? "" : (health.llm.error || "Model not ready");
    $("#brand-sub").textContent = `Brochure intelligence \u00b7 powered by OpenAI ${health.chat_model}`;
    $("#step5").textContent =
      `${health.embed_model} embeddings \u2192 ChromaDB (${health.chunks_indexed} chunks), metadata filters + BM25`;
  } catch {
    box.classList.remove("ok");
    box.classList.add("bad");
    text.textContent = "Server offline";
  }
}
