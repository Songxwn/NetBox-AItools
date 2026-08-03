(() => {
  const $ = (sel) => document.querySelector(sel);
  const messagesEl = $("#messages");
  const welcomeEl = $("#welcome");
  const form = $("#chatForm");
  const input = $("#input");
  const btnSend = $("#btnSend");
  const mcpBadge = $("#mcpBadge");
  const modelHint = $("#modelHint");

  let sessionId = localStorage.getItem("netbox_ai_session") || null;
  let busy = false;

  function showChat() {
    welcomeEl.hidden = true;
    messagesEl.hidden = false;
  }

  function appendMessage(role, text, extraClass = "") {
    showChat();
    const el = document.createElement("div");
    el.className = `msg ${role} ${extraClass}`.trim();
    if (role === "tool") {
      el.innerHTML = `<span class="label">MCP 工具</span>`;
      el.append(document.createTextNode(text));
    } else if (role === "assistant") {
      el.innerHTML = `<span class="label">回答</span>`;
      el.append(document.createTextNode(text));
    } else {
      el.textContent = text;
    }
    messagesEl.appendChild(el);
    el.scrollIntoView({ behavior: "smooth", block: "end" });
    return el;
  }

  function setBusy(v) {
    busy = v;
    btnSend.disabled = v;
    input.disabled = v;
  }

  function applyStatus(data) {
    mcpBadge.textContent = data.mcp_connected
      ? `MCP · 已连接${data.tools?.length ? `（${data.tools.length} 工具）` : ""}`
      : "MCP · 未连接";
    mcpBadge.classList.toggle("ok", !!data.mcp_connected);

    if (!data.ai_configured) {
      modelHint.textContent = "后台未配置 AI（请检查 .env / config.yaml）";
    } else {
      modelHint.textContent = `${data.ai_model || "未配置模型"} @ ${data.ai_base_url || "-"}`;
    }
  }

  async function loadStatus() {
    const res = await fetch("/api/status");
    const data = await res.json();
    applyStatus(data);
    return data;
  }

  async function resetChat() {
    const res = await fetch("/api/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
    const data = await res.json();
    sessionId = data.session_id;
    localStorage.setItem("netbox_ai_session", sessionId);
    messagesEl.innerHTML = "";
    messagesEl.hidden = true;
    welcomeEl.hidden = false;
  }

  async function sendMessage(text) {
    if (!text || busy) return;
    setBusy(true);
    appendMessage("user", text);
    input.value = "";
    autosize();

    const thinking = appendMessage("assistant", "正在查询…", "thinking");
    thinking.querySelector(".label")?.remove();

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: sessionId }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `请求失败 (${res.status})`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() || "";

        for (const chunk of chunks) {
          const line = chunk.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          const event = JSON.parse(line.slice(6));
          handleEvent(event, thinking);
        }
      }
    } catch (err) {
      thinking.remove();
      appendMessage("assistant", String(err.message || err), "error");
    } finally {
      if (thinking.isConnected && thinking.classList.contains("thinking")) {
        thinking.remove();
      }
      setBusy(false);
      input.focus();
      loadStatus().catch(() => {});
    }
  }

  function handleEvent(event, thinkingEl) {
    if (event.type === "session" && event.session_id) {
      sessionId = event.session_id;
      localStorage.setItem("netbox_ai_session", sessionId);
      return;
    }
    if (event.type === "status") {
      thinkingEl.textContent = event.message || "处理中…";
      return;
    }
    if (event.type === "tool_call") {
      appendMessage(
        "tool",
        `→ ${event.name}\n${JSON.stringify(event.arguments || {}, null, 2)}`
      );
      return;
    }
    if (event.type === "tool_result") {
      appendMessage("tool", `← ${event.name}\n${event.preview || ""}`);
      return;
    }
    if (event.type === "tool_error") {
      appendMessage("tool", `✗ ${event.name}\n${event.error || ""}`);
      return;
    }
    if (event.type === "answer" || event.type === "done") {
      thinkingEl.remove();
      if (event.content) appendMessage("assistant", event.content);
      if (event.session_id) {
        sessionId = event.session_id;
        localStorage.setItem("netbox_ai_session", sessionId);
      }
      return;
    }
    if (event.type === "error") {
      thinkingEl.remove();
      appendMessage("assistant", event.message || "未知错误", "error");
    }
  }

  function autosize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    sendMessage(input.value.trim());
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
  input.addEventListener("input", autosize);

  $("#suggestions").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-q]");
    if (!btn) return;
    sendMessage(btn.dataset.q);
  });

  $("#btnReset").addEventListener("click", () => resetChat());

  loadStatus().catch((err) => {
    modelHint.textContent = `状态加载失败: ${err.message || err}`;
  });
})();
