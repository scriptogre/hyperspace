(() => {
    htmx.registerExtension('hx-latency', {
        htmx_config_request: (_, {ctx}) => {
            const configuration = {delay: 0}
            htmx.trigger(
                document,
                'htmx:request:latency:configuration',
                configuration,
            )

            const fetch = ctx.fetch ?? window.fetch.bind(window)
            ctx.fetch = async (...args) => {
                if (configuration.delay > 0) await htmx.timeout(configuration.delay)

                const started = performance.now()
                const response = await fetch(...args)
                htmx.trigger(document, 'htmx:request:latency:measurement', {
                    ms: Math.round(performance.now() - started),
                })
                return response
            }
        }
    })
})()
