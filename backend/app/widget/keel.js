(function () {
  var script = document.currentScript;
  var api = (script && script.getAttribute("data-api")) || (script && script.src ? new URL(script.src).origin : window.location.origin);
  var root = document.createElement("div");
  root.setAttribute("data-keel-widget", "");
  var shadow = root.attachShadow({ mode: "open" });
  shadow.innerHTML = [
    "<style>",
    ":host { all: initial; }",
    ".wrap { font-family: 'Avenir Next', 'Segoe UI', Helvetica, sans-serif; color: #14201c; }",
    ".launch { position: fixed; right: 20px; bottom: 20px; z-index: 2147483000; border: 0; background: #14332c; color: #f4f6f2; height: 48px; padding: 0 16px; border-radius: 999px; font: 600 15px/1 'Avenir Next', 'Segoe UI', sans-serif; letter-spacing: 0.01em; cursor: pointer; box-shadow: 0 10px 24px rgba(20, 32, 28, 0.22); }",
    ".launch:focus-visible { outline: 2px solid #d6e36a; outline-offset: 3px; }",
    ".panel { position: fixed; right: 20px; bottom: 80px; z-index: 2147483000; width: min(380px, calc(100vw - 24px)); height: min(560px, calc(100vh - 110px)); background: #f7f8f5; color: #14201c; border: 1px solid #c9cfc8; border-radius: 18px; box-shadow: 0 18px 50px rgba(20, 32, 28, 0.2); display: none; flex-direction: column; overflow: hidden; }",
    ".panel.open { display: flex; }",
    "header { background: #14332c; color: #f4f6f2; padding: 14px 16px 12px; display: flex; justify-content: space-between; gap: 12px; }",
    "header strong { display: block; font-size: 15px; font-weight: 650; }",
    "header span { display: block; margin-top: 2px; color: #d5ddd6; font-size: 12px; }",
    "header button { background: transparent; color: #f4f6f2; border: 0; font-size: 20px; cursor: pointer; }",
    ".banner { margin: 10px 12px 0; background: #f3e56b; color: #14201c; border-radius: 10px; padding: 8px 10px; font-size: 12px; line-height: 1.4; }",
    ".log { flex: 1; overflow: auto; padding: 12px; display: flex; flex-direction: column; gap: 8px; }",
    ".bubble { max-width: 88%; padding: 9px 11px; border-radius: 12px; font-size: 14px; line-height: 1.45; white-space: pre-wrap; }",
    ".customer { align-self: flex-end; background: #14332c; color: #f4f6f2; }",
    ".agent { align-self: flex-start; background: #e7ebe4; color: #14201c; }",
    ".votes { align-self: flex-start; display: flex; gap: 6px; }",
    ".votes button, form button { border: 1px solid #c9cfc8; background: #fff; border-radius: 999px; padding: 4px 8px; cursor: pointer; font: 600 12px/1 inherit; }",
    "form { display: flex; gap: 8px; padding: 10px; border-top: 1px solid #d5dbd3; background: #fff; }",
    "input { flex: 1; border: 1px solid #c9cfc8; border-radius: 10px; padding: 10px; font: 14px/1.3 inherit; color: #14201c; background: #fff; }",
    "form button.send { background: #14332c; color: #f4f6f2; border: 0; border-radius: 10px; padding: 0 12px; }",
    "button:disabled { opacity: 0.55; cursor: default; }",
    "@media (max-width: 640px) { .panel { right: 8px; left: 8px; width: auto; bottom: 76px; } }",
    "</style>",
    "<div class='wrap'>",
    "<button class='launch' type='button'>Help</button>",
    "<section class='panel' role='dialog' aria-label='Marlow and Hale support'>",
    "<header><div><strong>Marlow & Hale</strong><span>Support by Keel</span></div><button type='button' aria-label='Close chat'>×</button></header>",
    "<div class='banner'>Demo mode: sample responses. Add your API key for live AI.</div>",
    "<div class='log' role='log' aria-live='polite'></div>",
    "<form><input aria-label='Message' placeholder='Ask about an order or a policy' maxlength='4000' /><button class='send' type='submit'>Send</button></form>",
    "</section></div>",
  ].join("");
  document.body.appendChild(root);
  var panel = shadow.querySelector(".panel");
  var log = shadow.querySelector(".log");
  var form = shadow.querySelector("form");
  var input = shadow.querySelector("input");
  var banner = shadow.querySelector(".banner");
  var conversationId = null;
  try { conversationId = localStorage.getItem("keel.conversation") || null; } catch (err) { conversationId = null; }

  shadow.querySelector(".launch").addEventListener("click", function () {
    panel.classList.add("open");
    input.focus();
  });
  shadow.querySelector("header button").addEventListener("click", function () {
    panel.classList.remove("open");
  });
  shadow.addEventListener("keydown", function (event) {
    if (event.key === "Escape") panel.classList.remove("open");
  });

  function add(role, text) {
    var bubble = document.createElement("div");
    bubble.className = "bubble " + role;
    bubble.textContent = text;
    log.appendChild(bubble);
    log.scrollTop = log.scrollHeight;
    return bubble;
  }

  function votes(conversation) {
    var row = document.createElement("div");
    row.className = "votes";
    ["up", "down"].forEach(function (vote) {
      var button = document.createElement("button");
      button.type = "button";
      button.textContent = vote === "up" ? "Helpful" : "Not helpful";
      button.addEventListener("click", function () {
        fetch(api + "/api/conversations/" + conversation + "/csat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ vote: vote }),
        }).then(function () {
          row.textContent = "Thanks. That vote is stored with this conversation.";
        });
      });
      row.appendChild(button);
    });
    log.appendChild(row);
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var text = input.value.trim();
    if (!text) return;
    input.value = "";
    add("customer", text);
    var send = form.querySelector(".send");
    send.disabled = true;
    var headers = { "Content-Type": "application/json" };
    try {
      var sessionKey = sessionStorage.getItem("keel.llmKey") || "";
      if (sessionKey) headers["X-Keel-LLM-Key"] = sessionKey;
    } catch (err) {}
    fetch(api + "/api/chat", {
      method: "POST",
      headers: headers,
      body: JSON.stringify({ message: text, conversation_id: conversationId }),
    })
      .then(function (response) { return response.json().then(function (body) { return { ok: response.ok, body: body }; }); })
      .then(function (result) {
        if (!result.ok) {
          add("agent", (result.body && result.body.detail) || "The support service didn't accept that message.");
          return;
        }
        conversationId = result.body.conversation_id;
        try { localStorage.setItem("keel.conversation", conversationId); } catch (err) {}
        if (result.body.mode === "demo") {
          banner.hidden = false;
          banner.textContent = "Demo mode: sample responses. Add your API key for live AI.";
        } else {
          banner.hidden = false;
          banner.textContent = "Live model for this tab. The key is not saved on the server.";
        }
        add("agent", result.body.reply);
        votes(conversationId);
      })
      .catch(function () {
        add("agent", "The support service is not responding.");
      })
      .finally(function () { send.disabled = false; input.focus(); });
  });
})();
