(function () {
  var ws = null;
  var ready = false;
  var TEXT = new TextDecoder();

  function connect() {
    ws = new WebSocket((location.protocol === "https:" ? "wss" : "ws") + "://" + location.host + "/ws");
    ws.binaryType = "arraybuffer";

    ws.onopen = function () { ready = true; };

    ws.onclose = function () {
      ready = false;
      setTimeout(connect, 1500);
    };

    ws.onerror = function () { ws.close(); };

    // Zstd-compressed batch of elements: morph/append/remove each by id,
    // dropping the ones flagged data-remove.
    ws.onmessage = function (e) {
      var html = TEXT.decode(fzstd.decompress(new Uint8Array(e.data)));
      var tpl = document.createElement("template");
      tpl.innerHTML = html;
      var node = tpl.content.firstElementChild;
      while (node) {
        var next = node.nextElementSibling;
        var existing = document.getElementById(node.id);
        if (node.hasAttribute("data-remove")) {
          if (existing) existing.remove();
        } else if (existing) {
          Idiomorph.morph(existing, node, MORPH_OPTS);
        } else {
          document.getElementById("cursors").appendChild(node);
        }
        node = next;
      }
    };
  }

  // Client-set attributes that drive optimistic UI (drag prediction, delete
  // pending). The server HTML never carries them, so morph must not wipe them.
  var IGNORE_ATTRS = {
    "data-grabbing": 1, "data-pending-delete": 1,
    "data-pred-x": 1, "data-pred-y": 1,
  };

  var MORPH_OPTS = {
    morphStyle: "outerHTML",
    callbacks: {
      // Bind hx-on/hx-live only on freshly inserted nodes, not the whole tree.
      afterNodeAdded: function (node) {
        if (node.nodeType === 1) htmx.process(node);
      },
      beforeAttributeUpdated: function (name, node) {
        if (IGNORE_ATTRS[name]) return false;
        // Preserve the client's own predicted cursor position through morphs.
        if (name === "style" && node.id === "cursor-" + document.body.dataset.session) return false;
        return true;
      },
    },
  };

  window.hyperspace = {
    call: function (fn, args) {
      if (!ws || !ready) return;
      ws.send(JSON.stringify({ fn: fn, args: args }));
    },
  };

  connect();
})();
