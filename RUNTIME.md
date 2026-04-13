# Runtime Management Rules

All widget microservices run under RuntimeManager.

RuntimeManager responsibilities:
- spawn service
- stop service
- restart failed service
- monitor health
- enforce timeouts
- emit lifecycle events

Failure policy:
- 3 restart attempts max
- exponential backoff
- mark failed after max retries

Every service must report:
- uptime
- health
- memory estimate
- last heartbeat
