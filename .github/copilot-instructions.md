# Project Guidelines

## Provider boundaries

- Keep `core/` and shared `integrations/` provider-agnostic. Do not add branches, lookups, labels, environment-variable names, or special cases keyed to a concrete provider name there.
- Put portal-specific behavior in that provider's module: login/session lifecycle, run options, browser requirements, credential metadata, invoice-date parsing, Drive naming, and provider-specific integrations.
- Expose optional behavior through the shared `Provider` contract as typed hooks or capabilities, with generic defaults where appropriate. Have the core orchestrate those hooks instead of using `if provider.name == ...`, `hasattr`, or provider-specific fallbacks.
- Keep shared integrations focused on generic mechanics and pass provider behavior through the contract rather than importing individual provider modules.
- When changing a provider behavior, search `core/`, `integrations/`, and other provider modules for duplicated or name-based handling; add tests that protect the boundary as well as the behavior.
