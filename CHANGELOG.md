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
- Location-aware shop selection: candidates are ranked by the user's market
  (`search.user_country`) and the LLM narrows the list. It can only narrow,
  never widen, and falls back to the deterministic ranking.
- Currency normalisation (`src/searcher/currency.py`): CZK, USD and GBP
  prices are converted to EUR, with the original amount kept on the deal.
- New `home` and `hobby` categories for furniture, DIY, garden and sport.
- 19 new registered sites: Autobazar.sk/.EU/.cz, Garáž.cz, TipCars, Auto.cz,
  mobile.de, OBI, Merkury Market, Stavebniny DEK, BAUHAUS, Hornbach, JYSK,
  FAVI.sk, IKEA, HERMAN, Hobbyshop.cz, Decathlon, Mironet.cz.
- CLI flags `--country` and `--max-sites` for `run`, `diamond-search` and
  `search`.

### Changed
- Site profiles are loaded at runtime; unknown adapters participate only when
  a validated profile exists.
- `search.default_filters` provides optional baseline filters below prompt and
  CLI precedence.
- `SiteSelectionAgent` reads the site registry instead of a hardcoded
  capability table.
- The Bazos adapter no longer requires a literal `€`, so it also works on
  bazos.cz.

### Fixed
- `discover_sites.py` honoured `--headless` and `--headed` backwards, so the
  browser never opened in headed mode.

### Verification
- Test suite: 333 passed, 11 skipped (live tests skipped by default).

## [1.0.0] - 2026-10-20

### Added
- Open-source community files and MIT license
