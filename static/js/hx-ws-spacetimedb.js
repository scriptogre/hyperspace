// STDB protocol layer on hx-ws: adds v1.json.spacetimedb subprotocol,
// auto-subscribes to html_broadcast, morphs server-pushed HTML into #app.
(function () {
  if (typeof htmx === "undefined") return;

  // Polyfill: dedupe hx-on listener init (htmx.process() stacks listeners on re-processed subtrees; pending upstream fix)
  htmx.on("htmx:before:on:init", function (e) {
    if (e.target._hxOnInitialized) { e.preventDefault(); return; }
    e.target._hxOnInitialized = true;
  });

  let api;
  let reqId = 1;
  let stdbConn = null;
  let token = localStorage.getItem("stdb_token");

  function isStdb(elt) {
    return elt && api && api.attributeValue(elt, "hx-ws-spacetimedb") != null;
  }

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

  function extractHtmlFromTableUpdate(tu) {
    if (!tu || tu.table_name !== "html_broadcast") return null;
    var updates = tu.updates || [];
    for (var j = 0; j < updates.length; j++) {
      var inserts = updates[j].inserts || [];
      for (var k = 0; k < inserts.length; k++) {
        var html = htmlFromRow(inserts[k]);
        if (html) return html;
      }
    }
    return null;
  }

  function extractHtml(msg) {
    if (msg.TransactionUpdate?.status?.Committed) {
      return extractHtmlFromTables(msg.TransactionUpdate.status.Committed.tables);
    }
    if (msg.TransactionUpdateLight?.update) {
      return extractHtmlFromTables(msg.TransactionUpdateLight.update.tables);
    }
    if (msg.SubscribeApplied) {
      var rows = msg.SubscribeApplied.rows;
      if (rows?.table_rows) {
        var html = extractHtmlFromTableUpdate(rows.table_rows);
        if (html) return html;
      }
      if (msg.SubscribeApplied.database_update) {
        return extractHtmlFromTables(msg.SubscribeApplied.database_update.tables);
      }
    }
    if (msg.InitialSubscription?.database_update) {
      return extractHtmlFromTables(msg.InitialSubscription.database_update.tables);
    }
    return null;
  }

  function subscribeHtmlBroadcast() {
    if (!stdbConn?.socket || stdbConn.socket.readyState !== WebSocket.OPEN) return;
    stdbConn.socket.send(JSON.stringify({
      SubscribeSingle: {
        query: "SELECT * FROM html_broadcast",
        request_id: reqId++,
        query_id: { id: 1 },
      },
    }));
  }

  window.stdb = {
    callReducer: function (name, args) {
      if (!stdbConn?.socket || stdbConn.socket.readyState !== WebSocket.OPEN) return;
      stdbConn.socket.send(JSON.stringify({
        CallReducer: { reducer: name, args: JSON.stringify(args), request_id: reqId++, flags: 0 },
      }));
    },
  };

  htmx.registerExtension("hx-ws-spacetimedb", {
    init: function (internalAPI) {
      api = internalAPI;
    },

    htmx_before_ws_connection: function (elt, detail) {
      if (!isStdb(elt)) return;
      detail.protocols = ["v1.json.spacetimedb"];
      if (token) {
        var u = new URL(detail.url);
        u.searchParams.set("token", token);
        detail.url = u.toString();
      }
    },

    htmx_after_ws_connection: function (elt, detail) {
      if (!isStdb(elt)) return;
      stdbConn = detail.connection;
    },

    htmx_ws_close: function (elt, detail) {
      if (!isStdb(elt)) return;
      if (stdbConn === detail.connection) stdbConn = null;
    },

    htmx_before_ws_message: function (elt, detail) {
      if (!isStdb(elt)) return;
      var msg = detail.message.json;
      if (!msg) return;

      if (msg.IdentityToken) {
        token = msg.IdentityToken.token;
        localStorage.setItem("stdb_token", token);
        subscribeHtmlBroadcast();
        detail.message.cancelled = true;
        return;
      }

      var html = extractHtml(msg);
      if (html) {
        var target = document.getElementById("app");
        if (target) htmx.swap({ target: target, swap: "innerMorph", text: html, transition: false });
      }
      // Cancel hx-ws default swap; we handle morph ourselves.
      detail.message.cancelled = true;
    },
  });
})();
