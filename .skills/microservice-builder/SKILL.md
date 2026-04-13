---
name: microservice-builder
description: Use when creating background Python services for GremlinBoard.
---

Build lightweight async microservices.

Required methods:
- start()
- stop()
- health()
- get_state()

Rules:
- no blocking loops
- minimal polling
- clean shutdown
- low memory use
- structured state output
