/**
 * htmx-spacetimedb.js — htmx extension for SpacetimeDB
 *
 * Bridges htmx's declarative attributes to SpacetimeDB's
 * v1.json.spacetimedb JSON text WebSocket protocol.
 *
 * Usage:
 *   <body hx-ext="spacetimedb" ws-connect="/v1/database/my_db/subscribe">
 *     <button ws-send hx-vals='{"_reducer":"create_brick","x":0,"y":0}'>Place</button>
 *   </body>
 *
 * Convention: auto-subscribes to `html_broadcast` table.
 * HTML from inserted rows is morphed into #app via Idiomorph.
 */
(function () {
  if (typeof htmx === "undefined") return;

  let ws = null;
  let reqId = 1;
  let token = localStorage.getItem("stdb_token");

  function send(msg) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg));
    }
  }

  function resolveWsUrl(url) {
    if (!url) return null;
    if (/^wss?:\/\//i.test(url)) return url;

    var resolved = new URL(url, window.location.href);
    resolved.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return resolved.toString();
  }

  function subscribe() {
    send({
      SubscribeSingle: {
        query: "SELECT * FROM html_broadcast",
        request_id: reqId++,
        query_id: { id: 1 },
      },
    });
  }

  function callReducer(name, args) {
    send({
      CallReducer: {
        reducer: name,
        args: JSON.stringify(args),
        request_id: reqId++,
        flags: 0,
      },
    });
  }

  /** Extract HTML from a row, handling both object and array formats. */
  function htmlFromRow(row) {
    var parsed = typeof row === "string" ? JSON.parse(row) : row;
    if (!parsed) return null;
    if (parsed.html) return parsed.html;
    if (Array.isArray(parsed)) {
      for (var i = parsed.length - 1; i >= 0; i--) {
        if (typeof parsed[i] === "string" && parsed[i].length > 10) return parsed[i];
      }
    }
    return null;
  }

  /** Extract html from inserts in a list of TableUpdate objects. */
  function extractHtmlFromTables(tables) {
    if (!tables) return null;
    for (var i = 0; i < tables.length; i++) {
      var table = tables[i];
      if (table.table_name !== "html_broadcast") continue;
      var updates = table.updates || [];
      for (var j = 0; j < updates.length; j++) {
        var inserts = updates[j].inserts || [];
        for (var k = 0; k < inserts.length; k++) {
          var html = htmlFromRow(inserts[k]);
          if (html) return html;
        }
      }
    }
    return null;
  }

  /** Extract html from a single TableUpdate (used by SubscribeApplied). */
  function extractHtmlFromTableUpdate(tableUpdate) {
    if (!tableUpdate || tableUpdate.table_name !== "html_broadcast") return null;
    var updates = tableUpdate.updates || [];
    for (var j = 0; j < updates.length; j++) {
      var inserts = updates[j].inserts || [];
      for (var k = 0; k < inserts.length; k++) {
        var html = htmlFromRow(inserts[k]);
        if (html) return html;
      }
    }
    return null;
  }

  function morphHtml(html) {
    var target = document.getElementById("app");
    if (!target || !html) return;
    if (typeof Idiomorph !== "undefined") {
      Idiomorph.morph(target, html, { morphStyle: "innerHTML" });
    } else {
      target.innerHTML = html;
    }
    // Let htmx process new/changed elements so hx-on:* handlers get attached
    htmx.process(target);
  }

  function handleServerMessage(data) {
    var msg = JSON.parse(data);

    if (msg.IdentityToken) {
      token = msg.IdentityToken.token;
      localStorage.setItem("stdb_token", token);
      subscribe();
      return;
    }

    var html = null;

    if (msg.TransactionUpdate) {
      var status = msg.TransactionUpdate.status;
      if (status && status.Committed) {
        html = extractHtmlFromTables(status.Committed.tables);
      }
    } else if (msg.TransactionUpdateLight) {
      var update = msg.TransactionUpdateLight.update;
      if (update) {
        html = extractHtmlFromTables(update.tables);
      }
    } else if (msg.SubscribeApplied) {
      var rows = msg.SubscribeApplied.rows;
      if (rows && rows.table_rows) {
        html = extractHtmlFromTableUpdate(rows.table_rows);
      }
      if (!html && msg.SubscribeApplied.database_update) {
        html = extractHtmlFromTables(msg.SubscribeApplied.database_update.tables);
      }
    } else if (msg.InitialSubscription) {
      var dbUpdate = msg.InitialSubscription.database_update;
      if (dbUpdate) {
        html = extractHtmlFromTables(dbUpdate.tables);
      }
    }

    if (html) morphHtml(html);
  }

  function connect(url) {
    if (ws) return;

    var wsUrl = resolveWsUrl(url);
    if (!wsUrl) return;
    if (token) {
      wsUrl += (wsUrl.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(token);
    }

    ws = new WebSocket(wsUrl, "v1.json.spacetimedb");

    var gotMessage = false;

    ws.onopen = function () {
      console.log("[stdb] connected");
    };

    ws.onmessage = function (e) {
      gotMessage = true;
      try {
        handleServerMessage(e.data);
      } catch (err) {
        console.error("[stdb] message error", err, e.data && e.data.slice && e.data.slice(0, 200));
      }
    };

    ws.onclose = function () {
      ws = null;
      // If we never got a message, the token is likely stale — clear it
      if (!gotMessage && token) {
        console.log("[stdb] connection failed with token, retrying without...");
        token = null;
        localStorage.removeItem("stdb_token");
        setTimeout(function () { connect(url); }, 100);
      } else {
        console.log("[stdb] disconnected, reconnecting in 2s...");
        setTimeout(function () { connect(url); }, 2000);
      }
    };

    ws.onerror = function (err) {
      console.error("[stdb] error", err);
    };
  }

  // Expose callReducer for use in hx-on:* inline handlers
  window.stdb = { callReducer: callReducer };

  htmx.defineExtension("spacetimedb", {
    onEvent: function (name, evt) {
      if (name === "htmx:afterProcessNode") {
        var elt = evt.detail.elt;
        if (elt && elt.getAttribute && elt.getAttribute("ws-connect")) {
          connect(elt.getAttribute("ws-connect"));
        }
      }
    },
  });
})();
