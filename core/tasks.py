import asyncio

def create_logged_task(coro, logger, name):
    task=asyncio.create_task(coro, name=name)
    def _done(t):
        try:
            exc=t.exception()
        except asyncio.CancelledError:
            return
        if exc:
            logger.error("%s failed: %s", name, exc, exc_info=exc)
    task.add_done_callback(_done)
    return task
