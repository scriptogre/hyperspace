(() => {
    htmx.registerExtension('hx-latency', {
        htmx_config_request: (_, {ctx}) => {
            const latency = document.querySelector('#latency')
            const delay = document.querySelector('#simulated-latency')
            if (!latency || !delay) return

            const fetch = ctx.fetch ?? window.fetch.bind(window)
            ctx.fetch = async (...args) => {
                if (delay.value !== '0') await htmx.timeout(delay.value)

                const started = performance.now()
                const response = await fetch(...args)
                latency.dataset.rtt = Math.round(performance.now() - started)
                return response
            }
        }
    })
})()
