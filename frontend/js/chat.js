/**
 * The conversation: sending a question and rendering the streamed answer.
 */
import { streamChat } from "./api.js";
import { answerFooter, guardrailPanel } from "./answer-meta.js";
import { BOT_ICON } from "./constants.js";
import { $, el, esc } from "./dom.js";
import { renderContextBar } from "./filters.js";
import { citedNumbers, renderMarkdown } from "./markdown.js";
import { showSources } from "./sources.js";
import { MAX_HISTORY, state } from "./state.js";

const TYPING = '<span class="typing"><span></span><span></span><span></span></span>' +
  '<span class="phase">Searching brochures&hellip;</span>';

function scrollToBottom() {
  const box = $("#messages");
  box.scrollTop = box.scrollHeight;
}

/** Append a chat bubble and return it. `html` must already be safe. */
function addMessage(role, html) {
  $("#welcome")?.remove();
  const message = el("div", `msg ${role}`);
  message.append(el("div", "avatar", role === "user" ? "You" : BOT_ICON), el("div", "bubble", html));
  $("#messages").append(message);
  scrollToBottom();
  return message.lastElementChild;
}

/** Toggle send/stop buttons while an answer is streaming. */
function setBusy(busy) {
  $("#send").hidden = busy;
  $("#stop").hidden = !busy;
  $("#input").disabled = busy;
}

/** Re-render the answer at most once per animation frame while tokens stream in. */
function frameRenderer(target) {
  let pending = false;
  return (text) => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => {
      pending = false;
      target.innerHTML = renderMarkdown(text) || target.innerHTML;
      scrollToBottom();
    });
  };
}

/** Stop the answer currently streaming, if any. */
export const stopAnswer = () => state.controller?.abort();

/**
 * Send a question and stream the answer into a new bubble.
 * Event order from the server: meta -> token* -> guardrails -> done.
 */
export async function ask(rawQuestion) {
  const question = rawQuestion.trim();
  if (!question || state.controller) return;

  addMessage("user", esc(question));
  const bubble = addMessage("bot", `<div class="answer">${TYPING}</div>`);
  const answerBox = bubble.querySelector(".answer");
  const answerIndex = state.answers.length;
  answerBox.dataset.answer = String(answerIndex);   // citations are clickable while streaming
  state.answers.push([]);

  const render = frameRenderer(answerBox);
  const result = { text: "", meta: null, outputChecks: [], timings: null, traceUrl: null };
  state.controller = new AbortController();
  setBusy(true);

  try {
    const body = {
      question, persona: state.persona, history: state.history,
      filters: state.filters, previous_filters: state.previousFilters,
    };
    for await (const event of streamChat(body, state.controller.signal)) {
      handleEvent(event, result, { answerBox, answerIndex, render });
    }
  } catch (err) {
    if (err.name === "AbortError") {
      result.text += result.text ? "\n\n*(stopped)*" : "*(stopped)*";
    } else {
      // Replace the typing indicator (keep any partial answer) with the error message.
      answerBox.innerHTML = `${renderMarkdown(result.text)}<div class="error-box">Something went wrong: ${esc(err.message)}</div>`;
      result.failed = true;
    }
  } finally {
    state.controller = null;
    setBusy(false);
  }

  finishAnswer(question, result, { bubble, answerBox, answerIndex });
}

/** Apply one streamed event to the UI and the running result. */
function handleEvent(event, result, { answerBox, answerIndex, render }) {
  switch (event.type) {
    case "meta": {
      result.meta = event;
      state.answers[answerIndex] = event.sources;
      showSources(event.sources, answerIndex);
      const phase = answerBox.querySelector(".phase");
      if (phase) phase.textContent = event.sources.length ? `Reading ${event.sources.length} excerpts\u2026` : "Thinking\u2026";
      break;
    }
    case "token":
      result.text += event.text;
      render(result.text);
      break;
    case "guardrails":
      result.outputChecks = event.checks;
      break;
    case "done":
      result.timings = event.timings;
      result.traceUrl = event.trace_url;
      break;
    default:
      break;
  }
}

/** Final render, footer, guardrails, cited-source ordering and conversation memory. */
function finishAnswer(question, result, { bubble, answerBox, answerIndex }) {
  const { text, meta } = result;
  if (text && !result.failed) answerBox.innerHTML = renderMarkdown(text);
  if (meta) {
    bubble.append(answerFooter(meta, result.timings, result.traceUrl));
    bubble.append(guardrailPanel([...(meta.checks || []), ...result.outputChecks]));
    state.cited[answerIndex] = citedNumbers(text);
    showSources(meta.sources, answerIndex);
    if (Object.keys(meta.filters || {}).length) state.previousFilters = meta.filters;
  }
  state.history.push({ role: "user", content: question }, { role: "assistant", content: text });
  state.history = state.history.slice(-MAX_HISTORY);
  renderContextBar();
  scrollToBottom();
  $("#input").focus();
}
