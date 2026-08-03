(() => {
  const $ = (sel) => document.querySelector(sel);
  const messagesEl = $("#messages");
  const welcomeEl = $("#welcome");
  const form = $("#chatForm");
  const input = $("#input");
  const btnSend = $("#btnSend");
  const mcpBadge = $("#mcpBadge");
  const modelHint = $("#modelHint");
  const settingsPanel = $("#settingsPanel");
  const settingsForm = $("#settingsForm");
  const settingsStatus = $("#settingsStatus");

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

  function applySettingsToUI(data) {
    settingsForm.ai_base_url.value = data.ai_base_url || "";
    settingsForm.ai_model.value = data.ai_model || "";
    settingsForm.temperature.value = data.temperature ?? 0.2;
    settingsForm.max_tokens.value = data.max_tokens ?? 4096;
    settingsForm.mcp_url.value = data.mcp_url || "";
    settingsForm.max_tool_rounds.value = data.max_tool_rounds ?? 8;
    settingsForm.ai_api_key.value = "";
    settingsForm.ai_api_key.placeholder = data.ai_api_key_set
      ? `已保存（${data.ai_api_key_masked}），留空保持不变`
      : "请输入 API Key";
    settingsForm.mcp_token.value = "";
    settingsForm.mcp_token.placeholder = data.mcp_token_set
      ? "已保存，留空保持；输入单个空格可清空"
      : "可选 Bearer Token";

    mcpBadge.textContent = data.mcp_connected
      ? `MCP · 已连接${data.tools?.length ? `（${data.tools.length} 工具）` : ""}`
      : "MCP · 未连接";
    mcpBadge.classList.toggle("ok", !!data.mcp_connected);
    modelHint.textContent = `${data.ai_model || "未配置模型"} @ ${data.ai_base_url || "-"}`;
  }

  async function loadSettings() {
    const res = await fetch("/api/settings");
    const data = await res.json();
    applySettingsToUI(data);
    return data;
  }

  function openSettings() {
    settingsPanel.hidden = false;
    settingsStatus.textContent = "";
    settingsStatus.className = "settings-status";
  }

  function closeSettings() {
    settingsPanel.hidden = true;
  }

  async function saveSettings(e) {
    e.preventDefault();
    settingsStatus.textContent = "保存中…";
    settingsStatus.className = "settings-status";

    const body = {
      ai_base_url: settingsForm.ai_base_url.value.trim() || null,
      ai_model: settingsForm.ai_model.value.trim() || null,
      mcp_url: settingsForm.mcp_url.value.trim() || null,
      temperature: Number(settingsForm.temperature.value),
      max_tokens: Number(settingsForm.max_tokens.value),
      max_tool_rounds: Number(settingsForm.max_tool_rounds.value),
    };

    const key = settingsForm.ai_api_key.value;
    if (key.trim()) body.ai_api_key = key.trim();

    const tokenRaw = settingsForm.mcp_token.value;
    if (tokenRaw.length > 0) {
      // 单个空格表示清空
      body.mcp_token = tokenRaw.trim();
    }

    try {
      const res = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "保存失败");
      applySettingsToUI(data);
      settingsStatus.textContent = data.mcp_connected ? "已保存，MCP 已连接" : "已保存";
      settingsStatus.className = "settings-status ok";
    } catch (err) {
      settingsStatus.textContent = String(err.message || err);
      settingsStatus.className = "settings-status err";
    }
  }

  async function reconnectOnly() {
    settingsStatus.textContent = "重连中…";
    try {
      const res = await fetch("/api/mcp/reconnect", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "重连失败");
      applySettingsToUI(data);
      settingsStatus.textContent = "MCP 已重连";
      settingsStatus.className = "settings-status ok";
    } catch (err) {
      settingsStatus.textContent = String(err.message || err);
      settingsStatus.className = "settings-status err";
    }
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

  $("#btnSettings").addEventListener("click", openSettings);
  $("#btnCloseSettings").addEventListener("click", closeSettings);
  $("#drawerBackdrop").addEventListener("click", closeSettings);
  $("#btnReset").addEventListener("click", () => resetChat());
  settingsForm.addEventListener("submit", saveSettings);
  $("#btnReconnect").addEventListener("click", reconnectOnly);

  loadSettings().catch((err) => {
    modelHint.textContent = `设置加载失败: ${err.message || err}`;
  });
})();
