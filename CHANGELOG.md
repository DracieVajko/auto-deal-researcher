# Changelog

## [Unreleased]

### Added
- Profile-driven site auto-mapping: `scripts/discover_sites.py` records search
  pages and filter controls, writes sanitized `src/searcher/site_profiles/*.yaml`
  maps, and validates them by replay.
- Generic `ProfileAdapter` plus profile-aware `BaseAdapter` hooks
  (`base_url`, `_goto_search`, `_apply_filters`).
- Canonical runtime filters (`min_price`, `max_price`, `condition`, `brand`,
  `location`, `shipping`, `seller_type`, `sort`, extras) with CLI flags,
  prompt/LLM extraction, and URL → UI → Python post-filter application.
- All 21 registered sites in `config.example.yaml`; Alza.cz and Bazos.cz reuse
  their adapters with configured country base URLs.

### Changed
- Site profiles are loaded at runtime; unknown adapters participate only when
  a validated profile exists.
- `search.default_filters` provides optional baseline filters below prompt and
  CLI precedence.

### Verification
- Test suite: 280 passed, 11 skipped (live tests skipped by default).

## [1.0.0] - 2026-10-20

### Added
- Open-source community files and MIT license
