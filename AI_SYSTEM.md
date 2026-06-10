# AI Generation System

AI generation flow:

idea
→ spec draft
→ validation
→ scaffold
→ codegen
→ review
→ install

No AI-generated code may directly deploy.

All providers implement:

generateSpec()
generateCode()
reviewCode()

Spec Studio provider selection is catalog-driven. The backend exposes each provider's available model IDs through `/api/ai/providers`, including richer `model_options` metadata when available:

- model label
- intelligence or reasoning effort choices
- speed/latency level
- catalog source (`provider_api` when discovered live, `fallback` when using maintained defaults)

Providers should discover live model availability from the provider API when local credentials are configured, then fall back to documented defaults so Spec Studio remains usable offline.
