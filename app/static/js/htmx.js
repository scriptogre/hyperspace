var htmx = (() => {

    /**
     * HCON, htmx's mini config language. Mirrors the JSON API.
     *
     * Used by hx-trigger, hx-swap, hx-vals, and other htmx config attributes.
     *
     * @see https://four.htmx.org/docs#hcon
     */
    const HCON = {
        /**
         * Parses an HCON string into an object.
         *
         * @example
         * HCON.parse('foo:1 bar:true');     // {foo: 1, bar: true}
         * HCON.parse('sse.mode:once');      // {sse: {mode: 'once'}}
         * HCON.parse('{"foo": 1}');         // {foo: 1}
         */
        parse(string) {
            if (!string) return {};
            if (string.startsWith('{')) return JSON.parse(string);
            let pattern = /(?:"([^"]+)"|'([^']+)'|([^\s,:]+))(?:\s*:\s*(?:"([^"]*)"|'([^']*)'|<((?:[^/]|\/(?!>))+)\/>|([^\s,]+)))?(?=\s|,|$)/g;
            let result = {};
            for (let match of string.matchAll(pattern)) {
                let [,
                    doubleQuotedKey,    // "key"
                    singleQuotedKey,    // 'key'
                    bareKey,            //  key
                    doubleQuotedValue,  // "value"
                    singleQuotedValue,  // 'value'
                    hyperscriptValue,   // <value/>
                    bareValue,          //  value
                ] = match;

                // pick this match's key and value forms
                let key = doubleQuotedKey ?? singleQuotedKey ?? bareKey;
                let value = (doubleQuotedValue ?? singleQuotedValue ?? hyperscriptValue ?? bareValue ?? 'true').trim();

                // JSON-parse if possible (e.g. "5" -> 5; "abc" stays string)
                try { value = JSON.parse(value); } catch {}

                // bare a.b -> {a:{b:...}}; quoted "a.b" -> {"a.b":...}
                let isDottedPath = bareKey?.includes('.');
                let pair = isDottedPath
                    ? key.split('.').reduceRight((acc, segment) => ({[segment]: acc}), value)
                    : {[key]: value};
                HCON.merge(pair, result);
            }
            return result;
        },

        /**
         * Splits an HCON-aware string at top-level commas.
         * Commas inside [], (), <.../>, "...", '...' are preserved.
         *
         * @example
         * HCON.split('a:1, b:2');                // ['a:1', ' b:2']
         * HCON.split('from:".a, .b", click');    // ['from:".a, .b"', ' click']
         */
        split(string) {
            return string.split(/,(?![^\[]*\])(?![^(]*\))(?![^<]*\/>)(?=(?:[^"']|"[^"]*"|'[^']*')*$)/);
        },

        /**
         * Deep-merges a source (HCON string or object) into a target.
         *
         * @example
         * HCON.merge({a: {b: 1}}, {a: {c: 2}});   // {a: {b: 1, c: 2}}
         * HCON.merge('a.b:1', {a: {c: 2}});       // {a: {b: 1, c: 2}}
         */
        merge(source, target) {
            if (typeof source === 'string') source = HCON.parse(source);

            for (let [key, val] of Object.entries(source)) {
                if (['__proto__', 'constructor', 'prototype'].includes(key)) continue;

                let sourceIsObject = val?.constructor === Object;
                let targetIsObject = target[key]?.constructor === Object;

                if (sourceIsObject && targetIsObject) {
                    HCON.merge(val, target[key]);
                } else {
                    target[key] = val;
                }
            }
            return target;
        },
    };

    class RequestQueue {
        #current = null   // {strategy, abort}
        #queue = []       // start callbacks for waiting requests

        // Returns "run", "queued", or "dropped".
        issue(strategy, abort, start) {
            if (!this.#current) {
                this.#current = {strategy, abort}
                return "run"
            }
            // Replace strategy OR current is abortable: abort current and run new
            if (strategy === "replace" || (strategy !== "abort" && this.#current.strategy === "abort")) {
                this.#queue = []
                this.#current.abort?.()
                this.#current = {strategy, abort}
                return "run"
            }
            if (strategy === "queue all") {
                this.#queue.push(start)
            } else if (strategy === "queue last") {
                this.#queue = [start]
            } else if (strategy !== "abort" && strategy !== "drop" && this.#queue.length === 0) {
                // default queue first
                this.#queue.push(start)
            } else {
                return "dropped"
            }
            return "queued"
        }

        finish() {
            this.#current = null
        }

        startNext() {
            this.#queue.shift()?.()
        }

        abort() {
            this.#current?.abort?.()
        }
    }

    class Htmx {

        #HCON = HCON
        #extMethods = new Map();
        #approvedExt = '';
        #registeredExt = new Set();
        #internalAPI;
        #Function = Function;
        #AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
        #ttPolicy = { createHTML: s => s, createScript: s => s };
        #actionSelector
        #boostSelector = "a,form";
        #hxOnQuery
        #transitionQueue
        #historyAbort
        #processingTransition

        constructor() {
            this.#initHtmxConfig();
            this.#initRequestIndicatorCss();
            this.#actionSelector = this.#prefixSelector('[hx-action],[hx-get],[hx-post],[hx-put],[hx-patch],[hx-delete]');
            this.#hxOnQuery = new XPathEvaluator().createExpression(`.//*[@*[${this.#prefixes("hx-on").map(p => `starts-with(name(), "${p}")`).join(' or ')}]]`);
            this.#internalAPI = {
                HCON,
                attributeValue: this.#attributeValue.bind(this),
                parseTriggerSpecs: this.#parseTriggerSpecs.bind(this),
                determineMethodAndAction: this.#determineMethodAndAction.bind(this),
                createRequestContext: this.#createRequestContext.bind(this),
                resolveTarget: this.#resolveTarget.bind(this),
                collectFormData: this.#collectFormData.bind(this),
                getAttributeObject: this.#getAttributeObject.bind(this),
                insertContent: this.#insertContent.bind(this),
                morph: this.#morph.bind(this),
                isSoftMatch: this.#isSoftMatch.bind(this),
                initSecurity: (ttPolicy, syncFn, asyncFn) => {
                    if (ttPolicy) this.#ttPolicy = ttPolicy;
                    if (syncFn) this.#Function = syncFn;
                    if (asyncFn) this.#AsyncFunction = asyncFn;
                },
                onTrigger: this.#onTrigger.bind(this),
                runActions: this.#runActions.bind(this),
                htmxProp: this.#htmxProp.bind(this),
                triggerHtmxEvent: this.#trigger.bind(this),
                executeJavaScript: this.#executeJavaScript.bind(this)
            };
            let init = () => {
                this.#initHistoryHandling()
                this.process(document.body)
            };
            if (document.readyState === 'loading') {
                document.addEventListener("DOMContentLoaded", init)
            } else {
                // wait a tick so extensions can register
                setTimeout(init)
            }
        }

        #initHtmxConfig() {
            this.version = '4.0.0-beta5'
            this.config = {
                logAll: false,
                prefix: "data-hx-",
                transitions: false,
                history: true,
                mode: 'same-origin',
                defaultSwap: "innerHTML",
                defaultSwapEmpty: true,
                defaultFocusScroll: false,
                indicatorClass: "htmx-indicator",
                requestClass: "htmx-request",
                includeIndicatorCSS: true,
                defaultTimeout: 60000, /* 60 second default timeout */
                extensions: '',
                morphIgnore: ["data-htmx-powered"],
                morphSkip: '[hx-morph-skip]',
                morphSkipChildren: '[hx-morph-skip-children]',
                morphScanLimit: 10,
                noSwap: [204, 304],
                implicitInheritance: false,
                defaultSettleDelay: 1
            }
            let metaConfig = document.querySelector('meta[name="htmx-config"]');
            if (metaConfig) {
                HCON.merge(metaConfig.content, this.config);
            }
            this.#approvedExt = this.config.extensions;
        }

        #initRequestIndicatorCss() {
            if (this.config.includeIndicatorCSS !== false) {
                let indicator = this.config.indicatorClass;
                let request = this.config.requestClass;
                let sheet = new CSSStyleSheet();
                sheet.replaceSync(
                    `.${indicator}{opacity:0;visibility: hidden} ` +
                    `.${request} .${indicator}, .${request}.${indicator}{opacity:1;visibility: visible;transition: opacity 200ms ease-in}`
                );
                document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
            }
        }

        registerExtension(name, extension) {
            if (this.#approvedExt && !this.#approvedExt.split(/,\s*/).includes(name)) return false;
            if (this.#registeredExt.has(name)) return false;
            this.#registeredExt.add(name);
            if (extension.init) extension.init(this.#internalAPI);
            Object.entries(extension).forEach(([key, value]) => {
                if(!this.#extMethods.get(key)?.push(value)) this.#extMethods.set(key, [value]);
            });
        }

        #ignore(elt) {
            let p = this.config.prefix;
            return !elt.closest || elt.closest('[hx-ignore]') != null || (p && elt.closest(`[${p}ignore]`) != null);
        }

        #attr(elt, name) {
            let p = this.config.prefix;
            return elt.getAttribute(name) ?? (p ? elt.getAttribute(name.replace('hx-', p)) : null);
        }

        #attrName(elt, name) {
            let p = this.config.prefix && name.replace('hx-', this.config.prefix);
            return elt.hasAttribute(name) ? name : (p && elt.hasAttribute(p) ? p : null);
        }

        #prefixSelector(s) {
            return this.#prefixes(s).join(',');
        }

        #prefixes(s) {
            let result = [s];
            if (this.config.prefix) result.push(s.replaceAll('hx-', this.config.prefix));
            return result;
        }

        #queryEltAndDescendants(elt, selector) {
            let results = [...(elt.querySelectorAll?.(selector) ?? [])];
            if (elt.matches?.(selector)) {
                results.unshift(elt);
            }
            return results;
        }

        #normalizeSwapStyle(style) {
            return style === 'before' ? 'beforebegin' :
                   style === 'after' ? 'afterend' :
                   style === 'prepend' ? 'afterbegin' :
                   style === 'append' ? 'beforeend' : style;
        }

        #findThisElements(elt, attrName) {
            let result = [];
            this.#attributeValue(elt, attrName, undefined, (val, elt) => {
                if (val?.split(/\s*[,:]\s*/).includes('this')) result.push(elt);
            });
            return result;
        }

        #attributeValue(elt, name, defaultVal, eltCollector) {
            name = this.#maybeAdjustMetaCharacter(name);
            let inherited = this.#maybeAdjustMetaCharacter(":inherited");
            let append = this.#maybeAdjustMetaCharacter(":append");

            let val = this.#attr(elt, name) ?? this.#attr(elt, name + inherited);
            if (val != null) return eltCollector ? eltCollector(val, elt) : val;

            let n1 = CSS.escape(this.config.implicitInheritance ? name : name + inherited);
            let n2 = CSS.escape(name + inherited + append);
            let inheritSelector = this.#prefixSelector(`[${n1}],[${n2}]`);
            let appendName = this.#attrName(elt, name + append) ?? this.#attrName(elt, name + inherited + append);
            if (appendName) {
                let appendValue = elt.getAttribute(appendName);
                let parent = elt.parentNode?.closest?.(inheritSelector);
                if (eltCollector) eltCollector(appendValue, elt);
                if (parent) {
                    let parentVal = this.#attributeValue(parent, name, undefined, eltCollector);
                    return parentVal ? (parentVal + "," + appendValue).replace(/[{}]/g, '') : appendValue;
                }
                return appendValue;
            }

            let parent = elt.parentNode?.closest?.(inheritSelector);
            if (parent) {
                val = this.#attributeValue(parent, name, undefined, eltCollector);
                if (!eltCollector && val && this.config.implicitInheritance) {
                    this.#triggerExtensions(elt, "htmx:after:implicitInheritance", {elt, name, parent})
                }
                return val;
            }
            return defaultVal;
        }

        #parseTriggerSpecs(spec) {
            return HCON.split(spec).flatMap(s => {
                let [,name,rest] = s.match(/^\s*(\S+\[[^\]]*\]|\S+)\s*(.*?)\s*$/) ?? [];
                if (!name) return [];  // skip empty/whitespace-only tokens
                if (/\[[^\]]*$/.test(name)) throw "unterminated:" + name;  // e.g. click[ctrlKey
                return [{name, ...HCON.parse(rest)}];  // spread modifiers (delay, throttle, etc.) onto result
            });
        }

        #determineMethodAndAction(elt, evt) {
            let hxMethod = this.#attributeValue(elt, "hx-method");
            let hxAction = this.#attributeValue(elt, "hx-action");

            let hxGet = this.#attributeValue(elt, "hx-get");
            let hxPost = this.#attributeValue(elt, "hx-post");
            let hxPut = this.#attributeValue(elt, "hx-put");
            let hxPatch = this.#attributeValue(elt, "hx-patch");
            let hxDelete = this.#attributeValue(elt, "hx-delete");

            let formMethod = evt.submitter?.getAttribute?.("formmethod") || elt.getAttribute("method");
            let formAction = evt.submitter?.getAttribute?.("formAction") || elt.getAttribute("action");
            let anchorHref = elt.getAttribute("href");

            return {
                action:
                    hxAction ||
                    (
                        hxGet ??
                        hxPost ??
                        hxPut ??
                        hxPatch ??
                        hxDelete
                    ) ||
                    this.#isBoosted(elt) && (anchorHref || formAction),

                method: (
                    hxMethod ||
                    (hxGet != null ? "GET" :
                    hxPost != null ? "POST" :
                    hxPut != null ? "PUT" :
                    hxPatch != null ? "PATCH" :
                    hxDelete != null && "DELETE") ||
                    formMethod ||
                    "GET"
                ).toUpperCase()
            };
        }

        #htmxProp(elt) {
            if (!elt._htmx) {
                elt._htmx = { listeners: [], triggerSpecs: [] };
                elt.setAttribute('data-htmx-powered', 'true');
            }
            return elt._htmx;
        }

        #htmxState(elt) {
            return elt._htmx_state ||= {};
        }

        #initializeElement(elt) {
            if (this.#shouldInitialize(elt) && this.#trigger(elt, "htmx:before:init", {}, true)) {
                let htmxProp = this.#htmxProp(elt);
                htmxProp.initialized = true;
                htmxProp.eventHandler = this.#createHtmxEventHandler(elt);
                this.#initializeTriggers(elt);
                this.#initializeAbortListener(elt)
                this.#trigger(elt, "htmx:after:init", {}, true)
            }
        }

        #createHtmxEventHandler(elt) {
            return async (evt) => {
                try {
                    let ctx = this.#createRequestContext(elt, evt);
                    await this.#handleTriggerEvent(ctx);
                } catch (e) {
                    this.#trigger(elt, 'htmx:error', { error: e });
                }
            };
        }

        #createRequestContext(sourceElement, sourceEvent, overrides = {}) {
            let {action, method} = this.#determineMethodAndAction(sourceElement, sourceEvent);
            let [fullAction, anchor] = (action || '').split('#');

            let hxSwap = this.#attributeValue(sourceElement, "hx-swap");
            let hxTarget = this.#attributeValue(sourceElement, "hx-target");
            let hxSelect = this.#attributeValue(sourceElement, "hx-select");
            let hxSelectOOB = this.#attributeValue(sourceElement, "hx-select-oob");
            let hxPushUrl = this.#attributeValue(sourceElement, "hx-push-url");
            let hxReplaceUrl = this.#attributeValue(sourceElement, "hx-replace-url");
            let hxConfirm = this.#attributeValue(sourceElement, "hx-confirm");
            let hxValidate = this.#attributeValue(sourceElement, "hx-validate", sourceElement.matches('form') && !sourceElement.noValidate && !sourceEvent.submitter?.formNoValidate ? "true" : "false");

            let defaultSwap = this.#parseSwapSpec(this.config.defaultSwap); // "innerHTML transition ..." -> {style, transition, ...}
            let attributeSwap = {
                ...(hxTarget !== undefined && {target: hxTarget}),
                ...(hxSelect !== undefined && {select: hxSelect}),
                ...(hxSelectOOB !== undefined && {selectOOB: hxSelectOOB}),
                ...this.#parseSwapSpec(hxSwap)
            };

            let ac = new AbortController();
            let ctx = {
                sourceElement,
                sourceEvent,
                confirm: hxConfirm,
                request: {
                    validate: hxValidate === "true",
                    action: fullAction,
                    anchor,
                    method,
                    headers: this.#createCoreHeaders(sourceElement),
                    abort: ac.abort.bind(ac),
                    credentials: "same-origin",
                    signal: ac.signal,
                    mode: this.config.mode
                },
                swap: {
                    content: undefined, // Populated from the response.
                    target: undefined,
                    style: undefined,
                    select: undefined,
                    selectOOB: undefined,
                    transition: this.config.transitions,
                    ...defaultSwap,
                    ...attributeSwap
                },
                actions: {
                    pushUrl: hxPushUrl,
                    replaceUrl: hxReplaceUrl
                }
            };

            let hxBoost = sourceElement._htmx?.boosted;
            if (hxBoost && hxBoost !== "true") {
                let {swap, ...swapOverrides} = HCON.parse(hxBoost);
                HCON.merge({
                    ...this.#parseSwapSpec(swap),
                    ...swapOverrides
                }, ctx.swap);
            }

            let {request: requestOverrides, ...contextOverrides} = overrides;
            HCON.merge(contextOverrides, ctx);

            let target = this.#resolveTarget(sourceElement, ctx.swap.target);
            ctx.request.headers["HX-Request-Type"] = (target === document.body || ctx.swap.select) ? "full" : "partial";
            if (target) {
                ctx.request.headers["HX-Target"] = this.#buildIdentifier(target);
            }

            // Apply hx-config overrides
            let hxConfig = this.#attributeValue(sourceElement, "hx-config");
            if (hxConfig) {
                HCON.merge(hxConfig, ctx.request);
                ctx.request.mode = this.config.mode;  // mode is security-sensitive, never allow per-element override
            }
            if (requestOverrides) HCON.merge(requestOverrides, ctx.request);
            return ctx;
        }

        #buildIdentifier(elt) {
            return `${elt.tagName.toLowerCase()}${elt.id ? '#' + encodeURI(elt.id) : ''}`;
        }

        #createCoreHeaders(elt) {
            let headers = {
                "HX-Request": "true",
                "HX-Source": this.#buildIdentifier(elt),
                "HX-Current-URL": location.href,
                "Accept": "text/html"
            };
            if (this.#isBoosted(elt)) {
                headers["HX-Boosted"] = "true"
            }
            return headers;
        }

        #handleHxHeaders(elt, ctx) {
            return this.#getAttributeObject(elt, "hx-headers", obj => {
                for (let key in obj) ctx.request.headers[key] = String(obj[key]);
            }, {ctx});
        }

        #resolveTarget(elt, selector) {
            if (selector instanceof Element) {
                return selector;
            } else if (selector != null) {
                return this.#findOrWarn(elt, selector, "hx-target");
            } else if (this.#isBoosted(elt)) {
                return document.body
            } else {
                return elt;
            }
        }

        #isBoosted(elt) {
            return elt?._htmx?.boosted;
        }

        async #handleTriggerEvent(ctx) {
            let elt = ctx.sourceElement
            let evt = ctx.sourceEvent
            if (!elt.isConnected) return

            if (this.#isModifierKeyClick(evt)) return

            if (this.#shouldCancel(evt)) evt.preventDefault()

            // determine if request uses query params
            let usesQueryParams = /GET|DELETE/.test(ctx.request.method);

            // Only include *enclosing* form info for request types that do not use
            // query parameters (can still be included explicitly with hx-include)
            let form = usesQueryParams
                ? (elt.matches('form') ? elt : null)
                : (elt.form || elt.closest("form"))

            // Build request body
            let body = this.#collectFormData(elt, form, evt.submitter, ctx.request.validate, usesQueryParams)
            if (!body) return  // Validation failed
            let valsResult = this.#getAttributeObject(elt, "hx-vals", obj => {
                ctx.vals = obj; // make available for json extensions
                for (let key in obj) body.set(key, obj[key]);
            }, {ctx});
            if (valsResult) await valsResult; // Only await if it returned a promise
            if (ctx.values) {
                for (let k in ctx.values) {
                    body.delete(k);
                    body.append(k, ctx.values[k]);
                }
            }

            // Handle dynamic headers
            let headersResult = this.#handleHxHeaders(elt, ctx)
            if (headersResult) await headersResult  // Only await if it returned a promise

            // Setup event-dependent request details
            Object.assign(ctx.request, {
                form,
                submitter: evt.submitter,
                body
            })

            if (!this.#trigger(elt, "htmx:config:request", {ctx: ctx})) return
            if (ctx.request.method === 'DIALOG') return

            let javascriptContent = this.#extractJavascriptContent(ctx.request.action);
            if (javascriptContent != null) {
                let data = Object.fromEntries(ctx.request.body);
                await this.#executeJavaScript(ctx.sourceElement, data, javascriptContent, false);
                return
            } else if (usesQueryParams) {
                let url = new URL(ctx.request.action, document.baseURI);

                for (let key of ctx.request.body.keys()) {
                    url.searchParams.delete(key);
                }
                for (let [key, value] of ctx.request.body) {
                    url.searchParams.append(key, value);
                }

                // Keep relative if same origin, otherwise use full URL
                if (url.origin === location.origin) {
                    ctx.request.action = url.pathname + url.search;
                } else {
                    ctx.request.action = url.href;
                }
                ctx.request.body = null;
            } else if ((this.#attributeValue(elt, "hx-encoding") ?? form?.enctype) !== "multipart/form-data") {
                ctx.request.body = new URLSearchParams(ctx.request.body);
            }

            await this.#issueRequest(ctx);
        }

        async #issueRequest(ctx) {
            let elt = ctx.sourceElement
            let syncStrategy = this.#determineSyncStrategy(elt);
            let requestQueue = this.#getRequestQueue(elt);

            if (requestQueue.issue(syncStrategy, () => ctx.request?.abort?.(), () => this.#issueRequest(ctx)) !== "run") return

            let indicators = [];
            let disableElements = [];
            try {
                // Handle confirmation
                if (ctx.confirm) {
                    let confirmed = await new Promise(resolve => {
                        let detail = {ctx, issueRequest: () => resolve(true), dropRequest: () => resolve(false)};
                        if (this.#trigger(elt, "htmx:confirm", detail)) {
                            let js = this.#extractJavascriptContent(ctx.confirm);
                            resolve(js ? this.#executeJavaScript(elt, {ctx}, js, true) : window.confirm(ctx.confirm));
                        }
                    });
                    if (!confirmed) return;
                }

                // initialize timeout & indicators after confirmation
                this.#initTimeout(ctx);
                indicators = this.#showIndicators(elt);
                disableElements = this.#disableElements(elt);

                ctx.fetch ||= window.fetch.bind(window)
                if (!this.#trigger(elt, "htmx:before:request", {ctx})) return;

                let response = await ctx.fetch(ctx.request.action, ctx.request);

                ctx.response = {
                    raw: response,
                    status: response.status,
                    headers: response.headers,
                }
                this.#trigger(elt, "htmx:after:request", {ctx});

                // Swap directives update ctx.swap; the rest are actions.
                let {retarget, reswap, reselect, ...headerActions} =
                    this.#extractActionsFromHeaders(ctx.response.headers);

                ctx.actions = {...ctx.actions, ...headerActions};

                // HX-Retarget & HX-Reselect
                if (retarget) ctx.swap.target = retarget;
                if (reselect) ctx.swap.select = reselect;

                // HX-Reswap
                if (reswap) {
                    // Preserve response content and selection; replace swap modifiers.
                    let {content, target, select, selectOOB} = ctx.swap;

                    ctx.swap = {
                        content, target, select, selectOOB,
                        transition: this.config.transitions,
                        ...this.#parseSwapSpec(this.config.defaultSwap),
                        ...this.#parseSwapSpec(reswap)
                    };
                }
                if (!this.#trigger(elt, "htmx:before:response", {ctx})) return;
                ctx.swap.content = await response.text();
                this.#trigger(elt, "htmx:after:response", {ctx});

                if (ctx.response.status >= 400) {
                    this.#trigger(elt, "htmx:response:error", {ctx})
                }

                let {swap: statusSwap, actions: statusActions} = this.#resolveStatusCode(
                    ctx.response,
                    ctx.sourceElement
                );
                ctx.swap = {...ctx.swap, ...statusSwap};
                ctx.actions = {...ctx.actions, ...statusActions};

                let {pushUrl, replaceUrl, ...otherActions} = ctx.actions;
                let historyAction = this.#resolveHistoryAction(
                    pushUrl,
                    replaceUrl,
                    this.#isBoosted(ctx.sourceElement),
                    ctx.response.raw.url || ctx.request.action,
                    ctx.request.anchor
                );
                ctx.actions = {...otherActions, ...historyAction};

                if (this.#runActions(ctx.actions, ctx.sourceElement, {ctx})) {
                    ctx.keepIndicators = true;
                    return
                }

                await this.#handleSwap(ctx);

            } catch (error) {
                this.#trigger(elt, "htmx:error", {ctx, error})
            } finally {
                clearTimeout(ctx.requestTimeout);
                if (!ctx.keepIndicators) {
                    this.#hideIndicators(indicators);
                    this.#enableElements(disableElements);
                }

                requestQueue.finish()
                this.#trigger(elt, "htmx:done", {ctx})
                requestQueue.startNext()
            }
        }

        /**
         * Extract camelCase actions from HX-* headers.
         * @example HX-Push-Url: /inbox, HX-Toast: Hello -> {pushUrl: '/inbox', toast: 'Hello'}
         */
        #extractActionsFromHeaders(headers) {
            let actions = {};
            for (let [name, value] of headers) {
                name = name.toLowerCase();
                if (name.startsWith('hx-')) {
                    actions[name.slice(3).replace(/-(\w)/g, (_, c) => c.toUpperCase())] = value;
                }
            }
            return actions;
        }

        /**
         * Run actions from HX-* headers or other sources.
         * @example runActions({trigger: 'chatUpdated', pushUrl: '/chat'}, elt)
         */
        #runActions(actions, element, detail = {}) {
            if (!Object.keys(actions).length) return false;

            detail = {...detail, actions};
            if (!this.#trigger(element, "htmx:before:actions", detail)) return false;

            let {
                trigger,
                refresh,
                redirect,
                location,
                pushUrl,
                replaceUrl
            } = detail.actions;

            if (trigger) {
                this.#runTriggerAction(trigger, element)
            }

            let shouldStop = true;

            if (refresh === 'true' || refresh === true) {
                this.#runNavigationAction('refresh');
            } else if (redirect) {
                this.#runNavigationAction('redirect', redirect);
            } else if (location) {
                this.#runNavigationAction('location', location);
            } else {
                shouldStop = false;
                if (pushUrl && pushUrl !== 'false') {
                    this.#runHistoryAction('push', pushUrl, element);
                } else if (replaceUrl && replaceUrl !== 'false') {
                    this.#runHistoryAction('replace', replaceUrl, element);
                }
            }

            this.#trigger(element, "htmx:after:actions", detail);
            return shouldStop;
        }

        #runTriggerAction(value, element) {
            // HX-Trigger: {...}
            if (value[0] === '{') {
                let triggers = HCON.parse(value);
                for (let name in triggers) {
                    let detail = triggers[name];
                    let target = detail?.target ? this.find(detail.target) : element;
                    this.trigger(target, name, typeof detail === 'object' ? detail : {value: detail});
                }
                return;
            }

            // HX-Trigger: event1, event2
            for (let name of value.split(',')) {
                this.trigger(element, name.trim(), {});
            }
        }

        #runHistoryAction(type, path, element) {
            if (!this.config.history) return;

            // true -> current URL
            if (path === 'true' || path === true) {
                path = location.pathname + location.search;
            }

            let detail = {
                history: {type, path},
                sourceElement: element
            };
            if (!this.#trigger(document, "htmx:before:history:update", detail)) return;

            path = detail.history.path;

            // HX-Push-Url
            if (type === 'push') {
                history.pushState({htmx: true}, '', path);
                this.#trigger(document, "htmx:after:history:push", {path});
            }

            // HX-Replace-Url
            if (type === 'replace') {
                history.replaceState({htmx: true}, '', path);
                this.#trigger(document, "htmx:after:history:replace", {path});
            }

            this.#trigger(document, "htmx:after:history:update", detail);
        }

        #runNavigationAction(type, value) {
            // HX-Refresh
            if (type === 'refresh') {
                location.reload();
                return;
            }

            // HX-Redirect
            if (type === 'redirect') {
                location.href = value;
                return;
            }

            // HX-Location
            if (type === 'location') {
                let hasAjaxOptions = value[0] === '{' || /[\s,]/.test(value);
                let {path, ...ajaxOptions} = hasAjaxOptions
                    ? HCON.parse(value)
                    : {path: value};
                if (ajaxOptions.replace == null) {
                    ajaxOptions.push ??= 'true';
                }
                this.ajax('GET', path, ajaxOptions);
            }
        }

        #initTimeout(ctx) {
            let timeout = ctx.request.timeout != null
                ? this.parseInterval(ctx.request.timeout)
                : this.config.defaultTimeout;
            if (timeout) {
                ctx.requestTimeout = setTimeout(() => ctx.request?.abort?.(), timeout);
            }
        }

        #determineSyncStrategy(elt) {
            let hxSync = this.#attributeValue(elt, "hx-sync");
            if (!hxSync) return "queue first";
            let strategy = hxSync.split(":").pop().trim();
            return /^(drop|abort|replace|queue)/.test(strategy) ? strategy : "queue first";
        }

        #getRequestQueue(elt) {
            let hxSync = this.#attributeValue(elt, "hx-sync");
            let syncElt = elt
            if (hxSync) {
                let selector = hxSync.includes(":")
                    ? hxSync.slice(0, hxSync.lastIndexOf(":")).trim()
                    : (/^(drop|abort|replace|queue)/.test(hxSync) ? null : hxSync);
                if (selector) syncElt = this.#findOrWarn(elt, selector, "hx-sync") || elt;
            }
            return this.#htmxState(syncElt).rq ||= new RequestQueue()
        }

        #isModifierKeyClick(evt) {
            return evt.type === 'click' && (evt.ctrlKey || evt.metaKey || evt.shiftKey)
                && !!evt.currentTarget?.closest?.('a[href]')
        }

        #shouldCancel(evt) {
            let elt = evt.currentTarget
            let isSubmit = evt.type === 'submit' && elt?.tagName === 'FORM'
            if (isSubmit) return true

            let isClick = evt.type === 'click' && evt.button === 0
            if (!isClick) return false

            let btn = elt?.closest?.('button, input[type="submit"], input[type="image"]')
            let form = btn?.form || btn?.closest('form')
            let isSubmitButton = btn && !btn.disabled && form &&
                (btn.type === 'submit' || btn.type === 'image' || (!btn.type && btn.tagName === 'BUTTON'))
            if (isSubmitButton) return true

            let link = elt?.closest?.('a')
            if (!link || !link.href) return false

            let href = link.getAttribute('href')
            let isFragmentOnly = href && href.startsWith('#') && href.length > 1
            return !isFragmentOnly
        }

        #initializeTriggers(elt, initialHandler = elt._htmx.eventHandler) {
            let hxTrigger = this.#attributeValue(elt, "hx-trigger");
            let trigger = hxTrigger || (elt.matches("form") ? "submit" :
                elt.matches("input:not([type=button]):not([type=submit]),select,textarea") ? "change" :
                    "click");
            this.#onTrigger(elt, trigger, initialHandler)
        }

        // Wire up event listeners with full modifier support (once, prevent, stop,
        // delay, throttle, changed, capture, passive, from, filter, etc.)
        #onTrigger(elt, specString, handler) {
            let specs = this.#parseTriggerSpecs(specString)
            this.#htmxProp(elt).triggerSpecs.push(...specs)

            for (let spec of specs) {
                spec.listeners = []

                let [eventName, filter] = this.#extractFilter(spec.name);

                // Resolve from: elements (self listens on elt but filters by event.target in guard)
                let fromElts = [elt];
                if (spec.from === 'outside') fromElts = [document];
                else if (spec.from && spec.from !== 'self') fromElts = this.#findAllExt(elt, spec.from);

                // Inner: runs after delay/throttle resolves
                let inner = (evt) => {
                    if (spec.halt || spec.prevent) evt.preventDefault();
                    if (spec.halt || spec.stop || spec.consume) evt.stopPropagation();
                    if (spec.once) {
                        for (let info of spec.listeners) info.fromElt.removeEventListener(info.eventName, info.handler, info);
                    }
                    handler(evt);
                };

                // Wrap inner with delay/throttle if needed
                let timed = inner;
                if (spec.delay) {
                    timed = evt => {
                        clearTimeout(spec.timeout);
                        spec.timeout = setTimeout(() => inner(evt), this.parseInterval(spec.delay));
                    };
                } else if (spec.throttle) {
                    timed = evt => {
                        if (spec.throttled) {
                            spec.throttledEvent = evt;
                        } else {
                            spec.throttled = true;
                            inner(evt);
                            spec.throttleTimeout = setTimeout(() => {
                                spec.throttled = false;
                                if (spec.throttledEvent) {
                                    let e = spec.throttledEvent;
                                    spec.throttledEvent = null;
                                    timed(e);
                                }
                            }, this.parseInterval(spec.throttle));
                        }
                    };
                }

                // Guarded: pre-timing checks that determine if event should proceed
                spec.handler = (evt) => {
                    if (spec.from === 'self' && evt.target !== elt) return;
                    if (spec.from === 'outside' && elt.contains(evt.target)) return;
                    if (spec.target && !evt.target?.matches?.(spec.target)) return;
                    if (spec.changed) {
                        let values = spec.values ??= new WeakMap();
                        let changed = false;
                        for (let fromElt of fromElts) {
                            if (values.get(fromElt) !== fromElt.value) {
                                changed = true;
                                values.set(fromElt, fromElt.value);
                            }
                        }
                        if (!changed) return;
                    }
                    if (filter) {
                        if (this.#shouldCancel(evt)) evt.preventDefault();
                        let evtArgs = {}; for (let k in evt) evtArgs[k] = evt[k];
                        if (!this.#executeJavaScript(elt, evtArgs, filter, true, false)) return;
                    }
                    timed(evt);
                };

                // Intersect/revealed: set up observer
                if (eventName === 'intersect' || eventName === 'revealed') {
                    let observerOptions = {rootMargin: spec.rootMargin};
                    if (spec.root) observerOptions.root = this.#findOrWarn(elt, spec.root);
                    if (spec.threshold) observerOptions.threshold = parseFloat(spec.threshold);
                    let isRevealed = eventName === 'revealed';
                    spec.observer = new IntersectionObserver((entries) => {
                        for (let i = 0; i < entries.length; i++) {
                            if (entries[i].isIntersecting) {
                                this.trigger(elt, 'intersect', {}, false);
                                if (isRevealed) spec.observer.disconnect();
                                break;
                            }
                        }
                    }, observerOptions);
                    eventName = 'intersect';
                    spec.observer.observe(elt);
                }

                // Every: set up interval
                if (eventName === "every") {
                    let interval = Object.keys(spec).find(k => k !== 'name');
                    spec.interval = setInterval(() => {
                        if (elt.isConnected) this.#trigger(elt, 'every', {}, false);
                        else clearInterval(spec.interval);
                    }, this.parseInterval(interval));
                }

                // Load: fire immediately, no listener needed
                if (eventName === 'load') {
                    spec.handler(new CustomEvent('load'));
                    continue;
                }

                // Register listeners
                for (let fromElt of fromElts) {
                    let listenerInfo = {fromElt, eventName, handler: spec.handler,
                        capture: !!spec.capture, passive: !!spec.passive};
                    elt._htmx.listeners.push(listenerInfo);
                    spec.listeners.push(listenerInfo);
                    fromElt.addEventListener(eventName, spec.handler, listenerInfo);
                }
            }
        }

        #extractFilter(str) {
            let match = str.match(/^([^\[]*)\[([^\]]*)]/);
            if (!match) return [str, null];
            return [match[1], match[2]];
        }

        #apiMethods(thisArg) {
            let bound = {};
            let proto = Object.getPrototypeOf(this);
            for (let name of Object.getOwnPropertyNames(proto)) {
                if (name !== 'constructor' && typeof this[name] === 'function') {
                    if (["find", "findAll"].includes(name)) {
                        bound[name] = (arg1, arg2) => {
                            if (arg2 === undefined) {
                                return this[name](thisArg, arg1)
                            } else {
                                return this[name](arg1, arg2)
                            }
                        }
                    } else {
                        bound[name] = this[name].bind(this);
                    }
                }
            }
            return bound;
        }

        #executeJavaScript(thisArg, obj, code, expression = true, isAsync = true) {
            let args = {}
            Object.assign(args, this.#apiMethods(thisArg))
            let scope = {};
            this.#triggerExtensions(thisArg, "htmx:scope", { scope });
            Object.assign(args, scope);
            Object.assign(args, obj)
            let keys = Object.keys(args);
            let values = Object.values(args);
            let FunctionConstructor = isAsync ? this.#AsyncFunction : this.#Function;
            let func = new FunctionConstructor(...keys, expression ? `return (${code})` : code);
            return func.call(thisArg, ...values);
        }

        /**
         * Initialize htmx attributes on root and all its descendants. When force is true, root
         * and every powered descendant are first torn down and re-wired from their current
         * attributes - use this after mutating hx-* attributes on an already-processed element.
         * @see https://four.htmx.org/reference/methods/htmx-process
         * @param {Element | ShadowRoot} root
         * @param {boolean} [force]
         */
        process(root, force) {
            if (!root?.isConnected) return;
            if (!(root instanceof Element)) { // ShadowRoot
                for (let elt of root.children || []) this.process(elt, force);
                return;
            }
            if (force) this.#cleanup(root, true);
            if (this.#ignore(root)) return;
            if (!this.#trigger(root, "htmx:before:process")) return
            let hxOnNodes = [root];
            let iter = this.#hxOnQuery.evaluate(root)
            let node = null
            while (node = iter.iterateNext()) hxOnNodes.push(node)
            for (let hxOnNode of hxOnNodes) {
                if (!this.#ignore(hxOnNode) && this.#trigger(hxOnNode, "htmx:before:on:init", {}, true)) {
                    this.#handleHxOnAttributes(hxOnNode);
                }
            }
            for (let elt of this.#queryEltAndDescendants(root, this.#actionSelector)) {
                this.#initializeElement(elt);
            }
            for (let elt of this.#queryEltAndDescendants(root, this.#boostSelector)) {
                this.#maybeBoost(elt);
            }
            this.#trigger(root, "htmx:after:process");
        }

        #maybeBoost(elt) {
            let hxBoost = this.#attributeValue(elt, "hx-boost");
            if (hxBoost && hxBoost !== "false" && this.#shouldBoost(elt) && this.#trigger(elt, "htmx:before:init", {}, true)) {
                let htmxProp = this.#htmxProp(elt);
                htmxProp.initialized = true;
                htmxProp.eventHandler = this.#createHtmxEventHandler(elt);
                htmxProp.boosted = hxBoost;
                let eventName = elt.matches('a') ? 'click' : 'submit';
                elt._htmx.listeners.push({fromElt: elt, eventName, handler: elt._htmx.eventHandler});
                elt.addEventListener(eventName, elt._htmx.eventHandler);
                this.#trigger(elt, "htmx:after:init", {}, true)
            }
        }

        #shouldBoost(elt) {
            if (this.#shouldInitialize(elt)) {
                if (elt.tagName === "A") {
                    if (elt.target === '' || elt.target === '_self') {
                        return !elt.hasAttribute('download') && !elt.getAttribute('href')?.startsWith?.("#") && this.#isSameOrigin(elt.href)
                    }
                } else if (elt.tagName === "FORM") {
                    return elt.method !== 'dialog' &&  this.#isSameOrigin(elt.action);
                }
            }
        }

        #isSameOrigin(url) {
            try {
                // URL constructor handles both relative and absolute URLs
                const parsed = new URL(url, window.location.href);
                return parsed.origin === window.location.origin;
            } catch (e) {
                // If URL parsing fails, assume not same-origin
                return false;
            }
        }

        #shouldInitialize(elt) {
            return !elt._htmx?.initialized && !this.#ignore(elt);
        }

        /**
         * Remove listeners, timers, and observers from elt and all its powered descendants.
         * When force is true, also delete their htmx state so a re-process fully re-initializes them.
         * @param {Element} elt
         * @param {boolean} [force]
         */
        #cleanup(elt, force) {
            let elts = [elt, ...elt.querySelectorAll?.('[data-htmx-powered]') ?? []];
            for (let e of elts) {
                if (!e._htmx) continue;
                this.#trigger(e, "htmx:before:cleanup")
                for (let spec of e._htmx.triggerSpecs || []) {
                    if (spec.interval) clearInterval(spec.interval);
                    if (spec.timeout) clearTimeout(spec.timeout);
                    if (spec.throttleTimeout) clearTimeout(spec.throttleTimeout);
                    spec.observer?.disconnect()
                }
                for (let info of e._htmx.listeners || []) {
                    info.fromElt.removeEventListener(info.eventName, info.handler, info);
                }
                e.removeAttribute('data-htmx-powered');
                this.#trigger(e, "htmx:after:cleanup")
                if (force) delete e._htmx;
            }
        }

        #handlePreservedElements(fragment) {
            let pantry = document.createElement('div');
            pantry.hidden = true;
            document.body.insertAdjacentElement('afterend', pantry);
            let newPreservedElts = fragment.querySelectorAll?.(this.#prefixSelector('[hx-preserve]')) || [];
            for (let preservedElt of newPreservedElts) {
                let currentElt = document.getElementById(preservedElt.id);
                if (currentElt) {
                    this.#moveBefore(pantry, currentElt, null);
                }
            }
            return pantry
        }

        #restorePreservedElements(pantry) {
            for (let preservedElt of [...pantry.children]) {
                let newElt = document.getElementById(preservedElt.id);
                if (newElt) {
                    this.#moveBefore(newElt.parentNode, preservedElt, newElt);
                    this.#cleanup(newElt)
                    newElt.remove()
                }
            }
            pantry.remove();
        }

        #parseHTML(resp) {
            let trusted = this.#ttPolicy.createHTML(resp);
            return Document.parseHTMLUnsafe?.(trusted) || new DOMParser().parseFromString(trusted, 'text/html');
        }

        #makeFragment(text) {
            // Convert <hx-*> tags (e.g. <hx-partial>, <hx-oob>) to <template hx type="*">
            let response = text.replace(/<hx-([a-z]+)(\s+|>)/gi, '<template hx type="$1"$2').replace(/<\/hx-[a-z]+>/gi, '</template>');
            let title = '';
            response = response.replace(/<head(\s[^>]*)?>[\s\S]*?<\/head>/i, m => (title = this.#parseHTML(m).title, ''));
            let startTag = response.match(/<([a-z][^\/>\x20\t\r\n\f]*)/i)?.[1]?.toLowerCase();

            let doc, fragment;
            if (startTag === 'html' || startTag === 'body') {
                doc = this.#parseHTML(response);
                fragment = document.createDocumentFragment();
                fragment.append(doc.body);
            } else {
                doc = this.#parseHTML(`<template>${response}</template>`);
                fragment = doc.querySelector('template').content;
            }

            if (!title) {
                let titleElt = fragment.querySelector('title:not(svg title)');
                if (titleElt) {
                    title = titleElt.textContent;
                    titleElt.remove();
                }
            }

            this.#processScripts(fragment);

            return {
                fragment,
                title
            };
        }

        #createOOBTask(tasks, elt, oobValue, sourceElement) {
            let targetSelector = elt.id ? '#' + CSS.escape(elt.id) : null;
            if (oobValue !== 'true' && oobValue && !oobValue.includes(' ')) {
                [oobValue, targetSelector = targetSelector] = oobValue.split(/:(.*)/);
            }
            if (oobValue === 'true' || !oobValue) oobValue = 'outerHTML';

            let swapSpec = {
                ...this.#parseSwapSpec(this.config.defaultSwap),
                ...this.#parseSwapSpec(oobValue)
            };
            targetSelector = swapSpec.target || targetSelector;
            swapSpec.strip ??= !swapSpec.style.startsWith('outer');
            if (!targetSelector) return;
            let targets = [...document.querySelectorAll(targetSelector)];
            for (let target of targets) {
                let fragment = document.createDocumentFragment();
                fragment.append(elt.cloneNode(true));
                tasks.push({type: 'oob', fragment, target, swapSpec, sourceElement});
            }
            elt.remove();
        }

        #processOOB(fragment, sourceElement, selectOOB) {
            let tasks = [];

            // Process hx-select-oob first (select elements from response)
            if (selectOOB) {
                for (let spec of selectOOB.split(',')) {
                    let [selector, oobValue = 'true'] = spec.split(/:(.*)/);
                    for (let elt of fragment.querySelectorAll(selector)) {
                        this.#createOOBTask(tasks, elt, oobValue, sourceElement);
                    }
                }
            }

            // Process elements with hx-swap-oob attribute
            for (let oobElt of fragment.querySelectorAll(this.#prefixSelector('[hx-swap-oob]'))) {
                let oobAttr = this.#attrName(oobElt, 'hx-swap-oob');
                let oobValue = oobElt.getAttribute(oobAttr);
                oobElt.removeAttribute(oobAttr);
                this.#createOOBTask(tasks, oobElt, oobValue, sourceElement);
            }
            return tasks;
        }

        #insertNodes(parent, before, fragment) {
            if (before) {
                before.before(...fragment.childNodes);
            } else {
                parent.append(...fragment.childNodes);
            }
        }

        #parseSwapSpec(value) {
            if (!value) return {};
            if (value.constructor === Object) return {...value};

            let swapStr = value.trim();
            let style;
            if (swapStr && !/^\S*:/.test(swapStr)) {
                let m = swapStr.match(/^(\S+)\s*(.*)$/);
                style = m[1];
                swapStr = m[2];
            }
            let {swap: swapDelay, settle: settleDelay, ...modifiers} = HCON.parse(swapStr);
            return {
                ...(style !== undefined && {style: this.#normalizeSwapStyle(style)}),
                ...(swapDelay !== undefined && {swapDelay}),
                ...(settleDelay !== undefined && {settleDelay}),
                ...modifiers
            };
        }

        #processPartials(fragment, ctx) {
            let tasks = [];

            for (let templateElt of fragment.querySelectorAll('template[hx]')) {
                let type = templateElt.getAttribute('type');
                
                if (type === 'partial') {
                    let targetSelector = this.#attr(templateElt, 'hx-target') || (templateElt.id ? '#' + CSS.escape(templateElt.id) : null);
                    if (targetSelector) {
                        this.#processScripts(templateElt.content);
                        let swapSpec = {
                            ...this.#parseSwapSpec(this.config.defaultSwap),
                            ...this.#parseSwapSpec(this.#attr(templateElt, 'hx-swap'))
                        };
                        for (let target of document.querySelectorAll(targetSelector)) {
                            tasks.push({
                                type: 'partial',
                                fragment: templateElt.content.cloneNode(true),
                                target,
                                swapSpec,
                                sourceElement: ctx.sourceElement
                            });
                        }
                    }
                } else {
                    this.#triggerExtensions(templateElt, 'htmx:process:' + type, { ctx, tasks });
                }
                templateElt.remove();
            }

            return tasks;
        }

        #setFocus(elt, options, start, end) {
            try {
                if (start != null && elt.setSelectionRange) {
                    elt.setSelectionRange(start, end);
                }
                elt.focus(options);
            } catch (e) {
                // setSelectionRange or Web component focus may fail so ignore
            }
        }

        #handleAutoFocus(elt) {
            let autofocus = this.#queryEltAndDescendants(elt, '[autofocus]')[0];
            if (autofocus) {
                this.#setFocus(autofocus);
            }
        }

        #handleScroll(swapSpec, target) {
            if (swapSpec.scroll) {
                let scrollTarget = swapSpec.scrollTarget ? this.#findExt(swapSpec.scrollTarget) : target;
                if (scrollTarget) {
                    if (swapSpec.scroll === 'top') {
                        scrollTarget.scrollTop = 0;
                    } else if (swapSpec.scroll === 'bottom'){
                        scrollTarget.scrollTop = scrollTarget.scrollHeight;
                    }
                }
            }
            if (swapSpec.show === 'top' || swapSpec.show === 'bottom') {
                let showTarget = swapSpec.showTarget ? this.#findExt(swapSpec.showTarget) : target;
                showTarget?.scrollIntoView?.(swapSpec.show === 'top')
            }
        }

        #handleAnchorScroll(ctx) {
            if (ctx.request?.anchor) {
                document.getElementById(ctx.request.anchor)?.scrollIntoView({block: 'start', behavior: 'auto'});
            }
        }

        #processScripts(container) {
            let scripts = this.#queryEltAndDescendants(container, 'script');
            for (let oldScript of scripts) {
                let newScript = document.createElement('script');
                for (let attr of oldScript.attributes) {
                    newScript.setAttribute(attr.name, attr.value);
                }
                if (this.config.inlineScriptNonce) {
                    newScript.nonce = this.config.inlineScriptNonce;
                }
                newScript.textContent = this.#ttPolicy.createScript(oldScript.textContent);
                oldScript.replaceWith(newScript);
            }
        }

        //============================================================================================
        // Public JS API
        //============================================================================================

        async swap(content, target, options = {}) {
            if (typeof options === 'string') options = {swap: options};

            let {source, swap, ...flatSwapOptions} = options;
            let sourceElement = typeof source === 'string' ? document.querySelector(source) : source;
            if (typeof source === 'string' && !sourceElement) {
                throw new Error('Source not found');
            }

            let targetElement = this.#resolveTarget(sourceElement || document.body, target);
            if (!targetElement) {
                throw new Error('Target not found');
            }
            sourceElement ||= targetElement;

            return this.#handleSwap({
                sourceElement,
                swap: {
                    content: undefined,
                    target: undefined,
                    style: undefined,
                    select: undefined,
                    selectOOB: undefined,
                    transition: this.config.transitions,
                    ...this.#parseSwapSpec(this.config.defaultSwap),
                    ...this.#parseSwapSpec(swap),
                    ...flatSwapOptions,
                    // positional arguments win
                    content,
                    target
                }
            });
        }

        async #handleSwap(ctx) {
            try {
                let {fragment, title} = this.#makeFragment(ctx.swap.content);
                ctx.title = title;
                let tasks = [];

                // Process OOB and partials
                let oobTasks = this.#processOOB(fragment, ctx.sourceElement, ctx.swap.selectOOB);
                let partialTasks = this.#processPartials(fragment, ctx);
                tasks.push(...oobTasks, ...partialTasks);

                // Process main swap first
                let mainSwap = this.#processMainSwap(ctx, fragment);
                if (mainSwap) {
                    tasks.unshift(mainSwap);
                }

                if(!this.#trigger(ctx.sourceElement, "htmx:before:swap", {ctx, tasks})){
                    return
                }

                let swapPromises = [];
                let transitionTasks = [];
                for (let task of tasks) {
                    if (task.swapSpec?.transition ?? mainSwap?.transition ?? ctx.swap.transition) {
                        transitionTasks.push(task);
                    } else {
                        swapPromises.push(this.#insertContent(task));
                    }
                }

                // submit all transition tasks in the transition queue w/no CSS transitions
                if (transitionTasks.length > 0) {
                    let tasksWrapper = async ()=> {
                        for (let task of transitionTasks) {
                            await this.#insertContent(task, false)
                        }
                    }
                    swapPromises.push(this.#submitTransitionTask(tasksWrapper));
                }

                await Promise.all(swapPromises);

                this.#trigger(ctx.sourceElement, "htmx:after:swap", {ctx});
                if (ctx.title && !mainSwap?.swapSpec?.ignoreTitle) document.title = ctx.title;
                this.#handleAnchorScroll(ctx);
            } finally {
                this.#trigger(ctx.sourceElement, "htmx:finally:swap", {ctx});
            }
        }

        #processMainSwap(ctx, fragment) {
            // Create main task if needed
            let swapSpec = {...ctx.swap};
            if (
                swapSpec.style === 'delete' ||    // delete always runs regardless of content
                fragment.childElementCount > 0 || // or fragment has elements
                fragment.textContent.trim() ||    // or fragment has text
                (swapSpec.swapEmpty ?? this.config.defaultSwapEmpty)
            ) {
                if (ctx.swap.select) {
                    let selected = fragment.querySelectorAll(ctx.swap.select);
                    fragment = document.createDocumentFragment();
                    fragment.append(...selected);
                }
                if (this.#isBoosted(ctx.sourceElement)) {
                    swapSpec.show ||= 'top';
                }
                let mainSwap = {
                    type: 'main',
                    fragment,
                    target: this.#resolveTarget(ctx.sourceElement || document.body, ctx.swap.target),
                    swapSpec,
                    sourceElement: ctx.sourceElement,
                    transition: ctx.swap.transition && swapSpec.transition !== false
                };
                return mainSwap;
            }
        }

        async #insertContent(task, cssTransition = true) {
            let {target, swapSpec, fragment} = task;
            if (typeof target === 'string') {
                target = document.querySelector(target);
            }
            if (!target) return;
            if (typeof swapSpec === 'string') {
                swapSpec = {
                    ...this.#parseSwapSpec(this.config.defaultSwap),
                    ...this.#parseSwapSpec(swapSpec)
                };
            }
            let swapStyle = swapSpec.style;
            if (swapStyle === 'none') return;
            // full-page response: fragment has a <body> wrapper — upgrade outerHTML to outerSync, strip for everything else
            if (fragment.firstElementChild?.tagName === 'BODY') {
                if (swapStyle === 'outerHTML') swapStyle = 'outerSync';
                else if (!swapStyle.startsWith('outer')) swapSpec.strip = true;
            }
            if (swapSpec.strip && fragment.firstElementChild) {
                fragment = document.createDocumentFragment();
                fragment.append(...(task.fragment.firstElementChild.content || task.fragment.firstElementChild).childNodes);
            }

            this.#addClass(target, "htmx-swapping")
            if (cssTransition && task.swapSpec?.swapDelay) {
                await this.timeout(task.swapSpec.swapDelay)
            }

            if (swapStyle === 'delete') {
                if (target.parentNode) {
                    this.#cleanup(target);
                    target.parentNode.removeChild(target);
                }
                return;
            }

            // innerHTML/outerHTML swaps backup focus and handle CSS transitions
            let focusInfo;
            let settleTasks = []
            let settleDelay = swapSpec.settleDelay ?? this.config.defaultSettleDelay;
            let parentNode = target.parentNode;
            if (swapStyle === 'innerHTML' || (swapStyle === 'outerHTML' && parentNode)) {
                let activeElt = document.activeElement;
                if (activeElt?.id) {
                    let start, end;
                    try { start = activeElt.selectionStart; end = activeElt.selectionEnd; } catch (e) {}
                    focusInfo = { elt: activeElt, start, end };
                }
                settleTasks = cssTransition && settleDelay ? this.#startCSSTransitions(fragment, target) : []
            }

            let pantry = this.#handlePreservedElements(fragment);
            let newContent = [...fragment.childNodes]
            try {
                if (swapStyle === 'innerHTML') {
                    for (const child of target.children) {
                        this.#cleanup(child)
                    }
                    target.replaceChildren(...fragment.childNodes);
                } else if (swapStyle === 'textContent') {
                    for (const child of target.querySelectorAll('[data-htmx-powered]')) {
                        this.#cleanup(child)
                    }
                    target.textContent = fragment.textContent;
                } else if (swapStyle === 'outerHTML') {
                    if (parentNode) {
                        this.#insertNodes(parentNode, target, fragment);
                        this.#cleanup(target)
                        parentNode.removeChild(target);
                        target = newContent[0] || parentNode
                    }
                } else if (swapStyle === 'outerSync') {
                    this.#copyAttributes(target, fragment.firstElementChild);
                    for (const child of target.children) {
                        this.#cleanup(child)
                    }
                    target.replaceChildren(...fragment.firstElementChild.childNodes);
                    newContent = [target];
                } else if (swapStyle === 'innerMorph') {
                    this.#morph(target, fragment, true);
                    newContent = [...target.childNodes];
                } else if (swapStyle === 'outerMorph') {
                    this.#morph(target, fragment, false);
                    newContent.push(target);
                } else if (swapStyle === 'beforebegin') {
                    if (parentNode) {
                        this.#insertNodes(parentNode, target, fragment);
                    }
                } else if (swapStyle === 'afterbegin') {
                    this.#insertNodes(target, target.firstChild, fragment);
                } else if (swapStyle === 'beforeend') {
                    this.#insertNodes(target, null, fragment);
                } else if (swapStyle === 'afterend') {
                    if (parentNode) {
                        this.#insertNodes(parentNode, target.nextSibling, fragment);
                    }
                } else {
                    let methods = this.#extMethods.get('handle_swap') || []
                    let handled = false;
                    for (const method of methods) {
                        let result = method(swapStyle, target, fragment, swapSpec);
                        if (result) {
                            handled = true;
                            if (Array.isArray(result)) {
                                newContent = result;
                            }
                            break;
                        }
                    }
                    if (!handled) {
                        throw new Error(`Unknown swap style: ${swapStyle}`);
                    }
                }
            } finally {
                this.#removeClass(target, "htmx-swapping")
            }
            this.#restorePreservedElements(pantry);
            if (focusInfo && !focusInfo.elt.matches(':focus')) {
                let newElt = document.getElementById(focusInfo.elt.id);
                if (newElt) {
                    let focusOptions = { preventScroll: swapSpec.focusScroll !== undefined ? !swapSpec.focusScroll : !this.config.defaultFocusScroll };
                    this.#setFocus(newElt, focusOptions, focusInfo.start, focusInfo.end);
                }
            }

            this.#trigger(target, "htmx:before:settle", {task, newContent, settleTasks})

            for (const elt of newContent) {
                this.#addClass(elt, "htmx-added")
            }

            if (cssTransition && settleTasks.length > 0) {
                this.#addClass(target, "htmx-settling")
                await this.timeout(settleDelay);
                // invoke settle tasks
                for (let settleTask of settleTasks) {
                    settleTask()
                }
                this.#removeClass(target, "htmx-settling")
            }

            this.#trigger(target, "htmx:after:settle", {task, newContent, settleTasks})

            for (const elt of newContent) {
                this.#removeClass(elt, "htmx-added")
                this.process(elt);
                this.#handleAutoFocus(elt);
            }
            
            this.#handleScroll(swapSpec, target);
        }

        #trigger(on, eventName, detail = {}, bubbles = true) {
            // Convention: events with detail.error log at error level, detail.warn at warn level,
            // otherwise at event level (gated by config.logAll). One emit per event.
            if (detail.error) {
                let prefix = `htmx: ${eventName}: ${detail.error.message ?? detail.error}`;
                if (detail.error instanceof Error) console.error(prefix, detail.error, { elt: on, detail });
                else console.error(prefix, { elt: on, detail });
            } else if (detail.warn) {
                console.warn(`htmx: ${eventName}: ${detail.warn}`, { elt: on, detail });
            } else if (this.config.logAll) {
                console.log(`htmx: ${eventName}`, { elt: on, detail });
            }
            on = this.#normalizeElement(on)
            this.#triggerExtensions(on, eventName, detail);
            return this.trigger(on, this.#maybeAdjustMetaCharacter(eventName), detail, bubbles)
        }

        #triggerExtensions(elt, eventName, detail = {}) {
            let methods = this.#extMethods.get(eventName.replace(/:/g, '_'))
            if (methods) {
                detail.cancelled = false;
                for (const fn of methods) {
                    if (fn(elt, detail) === false || detail.cancelled) {
                        detail.cancelled = true;
                        return false;
                    }
                }
            }
            return true;
        }

        timeout(time) {
            time = this.parseInterval(time);
            if (time > 0) {
                return new Promise(resolve => setTimeout(resolve, time));
            }
        }

        onLoad(callback) {
            this.on(this.#maybeAdjustMetaCharacter("htmx:after:process"), (evt) => {
                callback(evt.target)
            })
        }

        on(eventOrElt, eventOrCallback, callback) {
            let event;
            let elt = document;
            if (callback === undefined) {
                event = eventOrElt;
                callback =  eventOrCallback
            } else {
                elt = this.#normalizeElement(eventOrElt);
                event = eventOrCallback;
            }
            elt.addEventListener(event, callback);
            return callback;
        }

        find(selectorOrElt, selector) {
            return this.#findExt(selectorOrElt, selector)
        }

        findAll(selectorOrElt, selector) {
            return this.#findAllExt(selectorOrElt, selector)
        }

        parseInterval(str) {
            if (typeof str === 'number') return str;
            let m = {ms: 1, s: 1000, m: 60000};
            let [, n, u] = str?.match(/^([\d.]+)(ms|s|m)?$/) || [];
            let v = parseFloat(n) * (m[u] || 1);
            return isNaN(v) ? undefined : v;
        }

        trigger(on, eventName, detail = {}, bubbles = true) {
            on = this.#normalizeElement(on)
            let evt = new CustomEvent(eventName, {
                detail,
                cancelable: true,
                bubbles,
                composed: true
            });
            let target = on?.isConnected ? on : document;
            let result = !detail.cancelled && target.dispatchEvent(evt);
            return result
        }
        ajax(verb, path, options) {
            if (!options || options instanceof Element || typeof options === 'string') {
                options = {target: options};
            }

            let {
                source,
                event,
                target,
                swap,
                select,
                selectOOB,
                transition,
                headers,
                request,
                push,
                replace,
                ...contextOverrides
            } = options;

            // push and replace are shorthands for the pushUrl and replaceUrl actions
            if (push !== undefined || replace !== undefined) {
                contextOverrides.actions = {pushUrl: push, replaceUrl: replace, ...contextOverrides.actions};
            }

            let sourceElement = typeof source === 'string'
                ? document.querySelector(source)
                : source;

            if (typeof source === 'string' && !sourceElement) {
                return Promise.reject(new Error('Source not found'));
            }

            let targetElement = target != null
                ? this.#resolveTarget(sourceElement || document.body, target)
                : null;

            if (target != null && !targetElement) {
                return Promise.reject(new Error('Target not found'));
            }

            sourceElement ||= targetElement || document.body;

            let ctx = this.#createRequestContext(sourceElement, event || {}, {
                ...contextOverrides,
                swap: {
                    ...(target != null && {target}),
                    ...(select !== undefined && {select}),
                    ...(selectOOB !== undefined && {selectOOB}),
                    ...(transition !== undefined && {transition}),
                    ...this.#parseSwapSpec(swap)
                },
                request: {
                    ...request,
                    action: path,
                    method: verb.toUpperCase(),
                    headers: {
                        ...request?.headers,
                        ...headers
                    }
                }
            });

            return this.#handleTriggerEvent(ctx);
        }

        //============================================================================================
        // History Support
        //============================================================================================

        #initHistoryHandling() {
            if (!this.config.history) return;
            if (!history.state) {
                history.replaceState({htmx: true}, '', location.href);
            }
            window.addEventListener('popstate', (event) => {
                if (event.state && event.state.htmx) {
                    this.#historyAbort?.abort();
                    this.#restoreHistory();
                }
            });
        }

        #restoreHistory(path) {
            path = path || location.pathname + location.search;
            let historyElt = document.querySelector(this.#prefixSelector('[hx-history-elt]')) || document.body;
            if (this.#trigger(document, "htmx:before:history:restore", {path, cacheMiss: true})) {
                if (this.config.history === "reload") {
                    location.reload();
                } else {
                    this.#historyAbort = new AbortController();
                    this.ajax('GET', path, {
                        target: historyElt,
                        swap: 'outerSync',
                        select: historyElt !== document.body ? this.#prefixSelector('[hx-history-elt]') : undefined,
                        request: {
                            headers: {'HX-History-Restore-Request': 'true'},
                            signal: this.#historyAbort.signal
                        }
                    });
                }
            }
        }

        #resolveHistoryAction(pushUrl, replaceUrl, boosted, finalUrl, anchor) {
            if (pushUrl == null && replaceUrl == null && boosted) {
                pushUrl = true;
            }

            if (pushUrl === 'false' || pushUrl === false) pushUrl = null;
            if (replaceUrl === 'false' || replaceUrl === false) replaceUrl = null;
            if (!pushUrl && !replaceUrl) return null;

            let type = pushUrl ? 'push' : 'replace';
            let path = pushUrl || replaceUrl;
            if (path === 'true' || path === true) {
                let url = new URL(finalUrl, location.href);
                path = url.pathname + url.search + (anchor ? '#' + anchor : '');
            }

            return {[type + 'Url']: path};
        }

        // hx-on:<event> binds to <event> directly
        // hx-on::<event> is shorthand for hx-on:htmx:<event> (htmx events)
        #handleHxOnAttributes(node) {
            if (node._htmx?.onInitialized) return;
            let hxOnNames = this.#prefixes("hx-on");
            let mc = this.config.metaCharacter || ':';
            let handler = (code) => async (evt) => {
                try {
                    await this.#executeJavaScript(node, { event: evt },
                        `with(event?.detail||{}){${code}}`, false);
                } catch (e) {
                    if (typeof e !== 'symbol') this.#trigger(node, 'htmx:error', { error: e });
                }
            };
            for (let attr of node.getAttributeNames()) {
                let prefix = hxOnNames.find(p => attr.startsWith(p));
                if (!prefix) continue;
                this.#htmxProp(node).onInitialized = true;
                let rest = attr.substring(prefix.length);
                let value = node.getAttribute(attr);
                // hx-on="click once -> doA(); blur -> doB()"
                if (!rest) {
                    for (let part of value.split(/;(?=[^;]*->)/)) {
                        let idx = part.indexOf('->');
                        if (idx !== -1) this.#onTrigger(node, part.substring(0, idx).trim(), handler(part.substring(idx + 2).trim()));
                    }
                    continue;
                }
                // hx-on:click="code" or hx-on::before:request="code"
                if (rest[0] !== mc) continue;
                let eventName = rest.substring(1);
                if (eventName.startsWith(mc)) eventName = 'htmx' + mc + eventName.substring(1);
                this.#onTrigger(node, eventName, handler(value));
            }
        }

        #showIndicators(elt) {
            let hxIndicator = this.#attributeValue(elt, "hx-indicator");
            let indicatorElements;
            if (!hxIndicator) {
                if (elt === document.body) return [];
                indicatorElements = [elt]
            } else {
                indicatorElements = this.#findAllExt(elt, hxIndicator, "hx-indicator");
            }
            for (const indicator of indicatorElements) {
                let s = this.#htmxState(indicator);
                s.rc = (s.rc || 0) + 1;
                this.#addClass(indicator, this.config.requestClass)
            }
            return indicatorElements
        }

        #hideIndicators(indicatorElements) {
            for (let indicator of indicatorElements) {
                let s = this.#htmxState(indicator);
                if (s.rc && --s.rc <= 0) {
                    this.#removeClass(indicator, this.config.requestClass);
                    delete s.rc;
                }
            }
        }

        #disableElements(elt) {
            let hxDisable = this.#attributeValue(elt, "hx-disable");
            let disabledElements = []
            if (hxDisable) {
                disabledElements = this.#findAllExt(elt, hxDisable, "hx-disable");
                for (let indicator of disabledElements) {
                    let s = this.#htmxState(indicator);
                    s.dc = (s.dc || 0) + 1;
                    indicator.disabled = true
                }
            }
            return disabledElements
        }

        #enableElements(disabledElements) {
            for (const indicator of disabledElements) {
                let s = this.#htmxState(indicator);
                if (s.dc && --s.dc <= 0) {
                    indicator.disabled = false
                    delete s.dc;
                }
            }
        }

        #collectFormData(elt, form, submitter, validate, isGet) {
            if (validate && form && !form.reportValidity()) return
            
            let formData = form ? new FormData(form) : new FormData()
            let included = form ? new Set(form.elements) : new Set()
            if (!form) {
                if (validate && elt.reportValidity && !elt.reportValidity()) return
                this.#addInputValues(elt, included, formData, isGet);
            }
            if (submitter && submitter.name) {
                formData.append(submitter.name, submitter.value)
                included.add(submitter);
            }
            let hxInclude = this.#attributeValue(elt, "hx-include");
            if (hxInclude) {
                for (let node of this.#findAllExt(elt, hxInclude)) {
                    if (validate && node.reportValidity && !node.reportValidity()) return
                    this.#addInputValues(node, included, formData);
                }
            }
            return formData
        }

        #addInputValues(elt, included, formData, isGet) {
            let tag = elt.tagName;
            let inputs = [];
            if (tag === 'BUTTON' || tag.includes('-')) {
                inputs = [elt]; // send own value only, never collect children
            } else if (['INPUT', 'SELECT', 'TEXTAREA', 'FIELDSET'].includes(tag) || !isGet) {
                inputs = this.#queryEltAndDescendants(elt, '[name]:not(button)');
            }
            // GET on non-form-control containers (div, etc.) sends nothing — use hx-include for explicit inclusion

            for (let input of inputs) {
                let name = input.name || input.getAttribute?.('name');
                if (!name || input.matches(':disabled') || included.has(input)) continue;
                included.add(input);

                let type = input.type;
                if (type === 'checkbox' || type === 'radio' || (input.tagName !== 'INPUT' && 'checked' in input)) {
                    // Only add if checked
                    if (input.checked) {
                        formData.append(name, input.value);
                    }
                } else if (type === 'file') {
                    // Add all selected files
                    for (let file of input.files) {
                        formData.append(name, file);
                    }
                } else if (type === 'select-multiple') {
                    // Add all selected options
                    for (let option of input.selectedOptions) {
                        formData.append(name, option.value);
                    }
                } else {
                    formData.append(name, input.value);
                }
            }
        }

        #getAttributeObject(elt, attrName, callback, scope = {}) {
            let hxAttr = this.#attributeValue(elt, attrName);
            if (!hxAttr) return null;

            let javascriptContent = this.#extractJavascriptContent(hxAttr);
            if (javascriptContent) {
                // Wrap in braces if not already wrapped (for htmx 2.x compatibility)
                if (javascriptContent.indexOf('{') !== 0) {
                    javascriptContent = '{' + javascriptContent + '}';
                }
                // Return promise for async evaluation
                return this.#executeJavaScript(elt, scope, javascriptContent, true).then(obj => {
                    callback(obj);
                });
            } else {
                // Synchronous path - return the parsed object directly
                callback(HCON.parse(hxAttr));
            }
        }

        #stringHyperscriptStyleSelector(selector) {
            let s = selector.trim();
            return s.startsWith('<') && s.endsWith('/>') ? s.slice(1, -2) : s;
        }

        #findAllExt(eltOrSelector, maybeSelector, thisAttr, global) {
            let selector = maybeSelector ?? eltOrSelector;
            let elt = maybeSelector ? this.#normalizeElement(eltOrSelector) : document;
            if (selector.startsWith('global ')) {
                return this.#findAllExt(elt, selector.slice(7), thisAttr, true);
            }
            let parts = selector ? HCON.split(selector) : [];
            let result = []
            let unprocessedParts = []
            for (const part of parts) {
                let selector = this.#stringHyperscriptStyleSelector(part)
                let item
                if (selector.startsWith('closest ')) {
                    item = elt.closest(selector.slice(8))
                } else if (selector.startsWith('find ')) {
                    item = elt.querySelector(selector.slice(5))
                } else if (selector.startsWith('findAll ')) {
                    result.push(...elt.querySelectorAll(selector.slice(8)))
                } else if (selector === 'next' || selector === 'nextElementSibling') {
                    item = elt.nextElementSibling
                } else if (selector.startsWith('next ')) {
                    item = this.#scanForwardQuery(elt, selector.slice(5), !!global)
                } else if (selector === 'previous' || selector === 'previousElementSibling') {
                    item = elt.previousElementSibling
                } else if (selector.startsWith('previous ')) {
                    item = this.#scanBackwardsQuery(elt, selector.slice(9), !!global)
                } else if (selector === 'document') {
                    item = document
                } else if (selector === 'window') {
                    item = window
                } else if (selector === 'body') {
                    item = document.body
                } else if (selector === 'host') {
                    item = (elt.getRootNode()).host
                } else if (selector === 'this') {
                    if (thisAttr) {
                        result.push(...this.#findThisElements(elt, thisAttr));
                        continue;
                    }
                    item = elt
                } else {
                    unprocessedParts.push(selector)
                }

                if (item) {
                    result.push(item)
                }
            }

            if (unprocessedParts.length > 0) {
                let standardSelector = unprocessedParts.join(',')
                let rootNode = this.#getRootNode(elt, !!global)
                result.push(...rootNode.querySelectorAll(standardSelector))
            }

            return [...new Set(result)]
        }

        #scanForwardQuery(start, match, global) {
            return this.#scanUntilComparison(this.#getRootNode(start, global).querySelectorAll(match), start, Node.DOCUMENT_POSITION_PRECEDING);
        }

        #scanBackwardsQuery(start, match, global) {
            let results = [...this.#getRootNode(start, global).querySelectorAll(match)].reverse()
            return this.#scanUntilComparison(results, start, Node.DOCUMENT_POSITION_FOLLOWING);
        }

        #scanUntilComparison(results, start, comparison) {
            for (const elt of results) {
                if (elt.compareDocumentPosition(start) === comparison) {
                    return elt
                }
            }
        }

        #getRootNode(elt, global) {
            if (elt.isConnected && elt.getRootNode) {
                return elt.getRootNode?.({composed: global})
            } else {
                return document
            }
        }

        #findOrWarn(elt, selector, thisAttr) {
            let result = this.#findAllExt(elt, selector, thisAttr)[0]
            if (!result) {
                console.warn(`htmx: '${selector}' on ${thisAttr} did not match any element`,
                    { elt, selector, attr: thisAttr });
            }
            return result
        }

        #findExt(eltOrSelector, selector, thisAttr) {
            return this.#findAllExt(eltOrSelector, selector, thisAttr)[0]
        }

        #extractJavascriptContent(string) {
            if (string != null) {
                if (string.startsWith("js:")) {
                    return string.substring(3);
                } else if (string.startsWith("javascript:")) {
                    return string.substring(11);
                }
            }
        }

        #initializeAbortListener(elt) {
            let handler = () => {
                let requestQueue = this.#getRequestQueue(elt);
                requestQueue.abort();
            };
            elt.addEventListener("htmx:abort", handler);
            elt._htmx.listeners.push({fromElt: elt, eventName: "htmx:abort", handler});
        }

        #morph(oldNode, fragment, innerHTML) {
            let {persistentIds, idMap} = this.#createIdMaps(oldNode, fragment);
            let pantry = document.createElement("div");
            pantry.hidden = true;
            document.body.after( pantry);
            let ctx = {target: oldNode, idMap, persistentIds, pantry, futureMatches: new WeakSet()};

            if (innerHTML) {
                this.#morphChildren(ctx, oldNode, fragment);
            } else {
                this.#morphChildren(ctx, oldNode.parentNode, fragment, oldNode, oldNode.nextSibling);
            }
            this.#cleanup(pantry)
            pantry.remove();
        }

        #morphChildren(ctx, oldParent, newParent, insertionPoint = null, endPoint = null) {
            if (oldParent instanceof HTMLTemplateElement && newParent instanceof HTMLTemplateElement) {
                oldParent = oldParent.content;
                newParent = newParent.content;
            }
            insertionPoint ||= oldParent.firstChild;

            let newChild = newParent.firstChild;
            while (newChild) {
                let matchedNode;
                if (insertionPoint && insertionPoint != endPoint) {
                    matchedNode = this.#findBestMatch(ctx, newChild, insertionPoint, endPoint);
                    if (matchedNode) {
                        if (matchedNode !== insertionPoint) {
                            let cursor = insertionPoint;
                            while (cursor && cursor !== matchedNode) {
                                let tempNode = cursor;
                                cursor = cursor.nextSibling;
                                // remove nodes unless they match upcoming content in which case move them to end for later use
                                if (tempNode instanceof Element && (ctx.idMap.has(tempNode) || this.#matchesUpcomingSibling(ctx, tempNode, newChild))) {
                                    this.#moveBefore(oldParent, tempNode, endPoint);
                                } else {
                                    this.#removeNode(ctx, tempNode);
                                }
                            }
                        }
                    }
                }

                if (!matchedNode && newChild instanceof Element && ctx.persistentIds.has(newChild.id)) {
                    let escapedId = CSS.escape(newChild.id);
                    matchedNode = (ctx.target.id === newChild.id && ctx.target) ||
                        ctx.target.querySelector(`[id="${escapedId}"]`) ||
                        ctx.pantry.querySelector(`[id="${escapedId}"]`);
                    let element = matchedNode;
                    while ((element = element.parentNode)) {
                        let idSet = ctx.idMap.get(element);
                        if (idSet) {
                            idSet.delete(matchedNode.id);
                            if (!idSet.size) ctx.idMap.delete(element);
                        }
                    }
                    this.#moveBefore(oldParent, matchedNode, insertionPoint);
                }

                if (matchedNode) {
                    this.#morphNode(matchedNode, newChild, ctx);
                    insertionPoint = matchedNode.nextSibling;
                    newChild = newChild.nextSibling;
                    continue;
                }

                let nextNewChild = newChild.nextSibling;
                if (ctx.idMap.has(newChild)) {
                    let placeholder = document.createElement(newChild.tagName);
                    oldParent.insertBefore(placeholder, insertionPoint);
                    this.#morphNode(placeholder, newChild, ctx);
                    this.process(placeholder);
                    insertionPoint = placeholder.nextSibling;
                } else {
                    oldParent.insertBefore(newChild, insertionPoint);
                    insertionPoint = newChild.nextSibling;
                }
                newChild = nextNewChild;
            }

            while (insertionPoint && insertionPoint != endPoint) {
                let tempNode = insertionPoint;
                insertionPoint = insertionPoint.nextSibling;
                this.#removeNode(ctx, tempNode);
            }
        }

        #matchesUpcomingSibling(ctx, oldElt, startNode) {
            if (ctx.futureMatches.has(oldElt)) return true;
            for (let sibling = startNode.nextSibling, i = 0; sibling && i < this.config.morphScanLimit; sibling = sibling.nextSibling, i++) {
                if (sibling instanceof Element && oldElt.isEqualNode(sibling)) {
                    ctx.futureMatches.add(oldElt);
                    return true;
                }
            }
            return false;
        }

        #findBestMatch(ctx, node, startPoint, endPoint) {
            // text nodes match positionally — patch in place via #morphNode, 3 = TEXT_NODE
            if (node.nodeType === 3) return startPoint?.nodeType === 3 ? startPoint : null;
            if (!(node instanceof Element)) return null;
            let softMatch = null, displaceMatchCount = 0, scanLimit = this.config.morphScanLimit;
            let newSet = ctx.idMap.get(node), nodeMatchCount = newSet?.size || 0;
            // If node has a non-persistent ID, insert instead of soft matching
            if (node.id && !newSet) return null;
            let cursor = startPoint;
            while (cursor && cursor != endPoint) {
                let oldSet = ctx.idMap.get(cursor);
                if (this.#internalAPI.isSoftMatch(cursor, node)) {
                    // Hard match: matching IDs found in both nodes
                    if (oldSet && newSet && [...oldSet].some(id => newSet.has(id))) return cursor;
                    if (!oldSet) {
                        // Exact match: nodes are identical
                        if (scanLimit > 0 && cursor.isEqualNode(node)) return cursor;
                        // Soft match: same tag/type, save as fallback
                        if (!softMatch) softMatch = cursor;
                    }
                }
                // Stop if too many ID elements would be displaced
                displaceMatchCount += oldSet?.size || 0;
                if (displaceMatchCount > nodeMatchCount) break;
                // Don't move elements containing a focused typeable input
                if (document.activeElement?.selectionStart != null && cursor.contains(document.activeElement)) break;
                // Stop scanning if limit reached and no IDs to match
                if (--scanLimit < 1 && nodeMatchCount === 0) break;
                cursor = cursor.nextSibling;
            }
            // Only return fallback softMatch if it does not match upcoming content
            if (softMatch && this.#matchesUpcomingSibling(ctx, softMatch, node)) return null;
            return softMatch;
        }

        #isSoftMatch(oldNode, newNode) {
            if (!(oldNode instanceof Element) || oldNode.tagName !== newNode.tagName) {
                return false;
            }
            // Script tags must be identical to match - never patch a script with different content
            if (oldNode.tagName === 'SCRIPT' && !oldNode.isEqualNode(newNode)) return false;
            return !oldNode.id || oldNode.id === newNode.id;
        }

        #removeNode(ctx, node) {
            if (ctx.idMap.has(node)) {
                this.#moveBefore(ctx.pantry, node, null);
            } else {
                this.#cleanup(node)
                node.remove();
            }
        }

        #moveBefore(parentNode, element, after) {
            if (parentNode.moveBefore) {
                try {
                    parentNode.moveBefore(element, after);
                    return
                } catch (e) {
                    // ignore and insertBefore instead
                }
            }
            parentNode.insertBefore(element, after);
        }

        #morphNode(oldNode, newNode, ctx) {
            if (oldNode.nodeType === 3) { // text node
                if (oldNode.nodeValue !== newNode.nodeValue) oldNode.nodeValue = newNode.nodeValue;
                return;
            }
            if (this.config.morphSkip && oldNode.matches?.(this.config.morphSkip)) return;
                
            // Trigger extension hook - if returns false, skip morphing this node
            if (!this.#triggerExtensions(oldNode, "htmx:before:morph:node", {oldNode, newNode})) return;
                
            this.#copyAttributes(oldNode, newNode);
            if (oldNode instanceof HTMLTextAreaElement && oldNode.defaultValue != newNode.defaultValue) {
                oldNode.value = newNode.value;
            }
            let skipChildren = this.config.morphSkipChildren && oldNode.matches?.(this.config.morphSkipChildren);
            // isEqualNode does not detect template content diff so always morph templates
            if (!skipChildren && (!oldNode.isEqualNode(newNode) || newNode.tagName === 'TEMPLATE' || newNode.querySelector?.('template'))) {
                this.#morphChildren(ctx, oldNode, newNode);
            }
        }

        #copyAttributes(destination, source) {
            let attributesToIgnore = this.config.morphIgnore || [];
            let needsReinit = false;
            let isHxAttr = name => this.#prefixes('hx-').some(p => name.startsWith(p));
            for (const attr of source.attributes) {
                if (!attributesToIgnore.some(p => attr.name.startsWith(p)) && destination.getAttribute(attr.name) !== attr.value) {
                    if (isHxAttr(attr.name)) needsReinit = true;
                    if (!this.#triggerExtensions(destination, 'htmx:before:morph:attr', { attrName: attr.name, newValue: attr.value })) continue;
                    destination.setAttribute(attr.name, attr.value);
                    if (attr.name === "value" && destination instanceof HTMLInputElement && destination.type !== "file") {
                        destination.value = attr.value;
                    }
                }
            }
            for (let i = destination.attributes.length - 1; i >= 0; i--) {
                let attr = destination.attributes[i];
                if (attr && !source.hasAttribute(attr.name) && !attributesToIgnore.some(p => attr.name.startsWith(p))) {
                    if (isHxAttr(attr.name)) needsReinit = true;
                    if (!this.#triggerExtensions(destination, 'htmx:before:morph:attr', { attrName: attr.name, newValue: null })) continue;
                    destination.removeAttribute(attr.name);
                }
            }
            if (needsReinit) this.#cleanup(destination, true);
        }

        #populateIdMapWithTree(idMap, persistentIds, root, elements) {
            for (const elt of elements) {
                if (persistentIds.has(elt.id)) {
                    let current = elt;
                    while (current && current !== root) {
                        let idSet = idMap.get(current);
                        if (idSet == null) {
                            idSet = new Set();
                            idMap.set(current, idSet);
                        }
                        idSet.add(elt.id);
                        current = current.parentElement;
                    }
                }
            }
        }

        #createIdMaps(oldNode, newContent) {
            let oldIdElements = this.#queryEltAndDescendants(oldNode, "[id]");
            let newIdElements = newContent.querySelectorAll("[id]");
            let persistentIds = this.#createPersistentIds(oldIdElements, newIdElements);
            let idMap = new Map();
            this.#populateIdMapWithTree(idMap, persistentIds, oldNode.parentElement, oldIdElements);
            this.#populateIdMapWithTree(idMap, persistentIds, newContent, newIdElements);
            return {persistentIds, idMap};
        }

        #createPersistentIds(oldIdElements, newIdElements) {
            let duplicateIds = new Set(), oldIdTagNameMap = new Map();
            for (const {id, tagName} of oldIdElements) {
                if (oldIdTagNameMap.has(id)) duplicateIds.add(id);
                else if (id) oldIdTagNameMap.set(id, tagName);
            }
            let persistentIds = new Set();
            for (const {id, tagName} of newIdElements) {
                if (persistentIds.has(id)) duplicateIds.add(id);
                else if (oldIdTagNameMap.get(id) === tagName) persistentIds.add(id);
            }
            for (const id of duplicateIds) persistentIds.delete(id);
            return persistentIds;
        }

        #resolveStatusCode(response, element) {
            let statusCode = String(response.status);

            let statusCodePatterns = [
                statusCode,                    // 404
                statusCode.slice(0, 2) + 'x',  // 40x
                statusCode[0] + 'xx'           // 4xx
            ];
            let noSwapPatterns = this.config.noSwap.map(String);

            for (let pattern of statusCodePatterns) {
                if (noSwapPatterns.includes(pattern)) {
                    return {swap: {style: 'none'}, actions: {}};
                }

                let hxStatus = this.#attributeValue(element, 'hx-status:' + pattern);
                if (!hxStatus) continue;

                let {swap, push, replace, ...swapOptions} = HCON.parse(hxStatus);
                let actions = {};
                let hasHistoryHeader =
                    response.headers?.get('HX-Push-Url') != null ||
                    response.headers?.get('HX-Replace-Url') != null;

                if (!hasHistoryHeader && (push !== undefined || replace !== undefined)) {
                    actions = {pushUrl: push, replaceUrl: replace};
                }

                return {
                    swap: {
                        ...this.#parseSwapSpec(swap),
                        ...swapOptions
                    },
                    actions
                };
            }

            return {swap: {}, actions: {}};
        }

        #submitTransitionTask(task) {
            return new Promise((resolve) => {
                this.#transitionQueue ||= [];
                this.#transitionQueue.push({ task, resolve });
                if (!this.#processingTransition) {
                    this.#processTransitionQueue();
                }
            });
        }

        async #processTransitionQueue() {
            if (this.#transitionQueue.length === 0 || this.#processingTransition) {
                return;
            }

            this.#processingTransition = true;
            let { task, resolve } = this.#transitionQueue.shift();

            try {
                if (document.startViewTransition) {
                    this.#trigger(document, "htmx:before:viewTransition", {task})
                    await document.startViewTransition(task).finished;
                    this.#trigger(document, "htmx:after:viewTransition", {task})
                } else {
                    await task();
                }
            } catch (e) {
                // Transitions can be skipped/aborted - this is normal
            } finally {
                this.#processingTransition = false;
                resolve();
                this.#processTransitionQueue();
            }
        }

        #startCSSTransitions(fragment, root) {
            let idElements = root.querySelectorAll("[id]");
            let existingElementsById = Object.fromEntries([...idElements].map(e => [e.id, e]));
            let newElementsWithIds = fragment.querySelectorAll("[id]");
            let restoreTasks = []
            for (let elt of newElementsWithIds) {
                let existing = existingElementsById[elt.id];
                if (existing?.tagName === elt.tagName) {
                    let clone = elt.cloneNode(false); // shallow clone node
                    this.#copyAttributes(elt, existing)
                    restoreTasks.push(()=>{
                        this.#copyAttributes(elt, clone)
                    })
                }
            }
            return restoreTasks;
        }

        #addClass(elt, cls) {
            elt?.classList?.add?.(cls);
        }

        #removeClass(elt, cls) {
            elt?.classList?.remove?.(cls);
            if (elt?.classList?.length === 0) elt.removeAttribute('class');
        }

        #normalizeElement(cssOrElement) {
            if (typeof cssOrElement === "string") {
                return this.find(cssOrElement);
            } else {
                return cssOrElement
            }
        }

        #maybeAdjustMetaCharacter(string) {
            if (this.config.metaCharacter) {
                return string.replace(/:/g, this.config.metaCharacter);
            } else {
                return string;
            }
        }

    }

    return new Htmx()
})()

;
