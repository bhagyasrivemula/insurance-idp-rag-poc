/**
 * All communication with the backend lives here.
 */

/**
 * GET/POST helper that returns parsed JSON or throws a readable error.
 * @param {string} url
 * @param {RequestInit} [options]
 */
export async function getJSON(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

/** POST a JSON body and return the parsed JSON response. */
export const postJSON = (url, body) =>
  getJSON(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const fetchHealth = () => getJSON("/api/health");
export const fetchProducts = () => getJSON("/api/products");
export const fetchPipeline = () => getJSON("/api/pipeline");
export const fetchEvaluation = () => getJSON("/api/evaluation");
export const searchChunks = (body) => postJSON("/api/search", body);

/** Link that opens a brochure PDF at a page. */
export const pdfUrl = (fileName, page) =>
  `/pdf/${encodeURIComponent(fileName)}${page ? `#page=${page}` : ""}`;

/**
 * Ask a question and stream the answer.
 * The server sends newline-delimited JSON events (meta, token, guardrails, done, error);
 * this async generator yields them one by one.
 *
 * @param {object} body - {question, persona, history, filters, previous_filters}
 * @param {AbortSignal} signal - lets the user stop the answer
 */
export async function* streamChat(body, signal) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw new Error(`Server error ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();                      // keep a partial line for the next read
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      if (event.type === "error") throw new Error(event.message);
      yield event;
    }
  }
}
