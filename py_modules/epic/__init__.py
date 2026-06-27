"""decky-epic backend package.

Modules:
  paths             — Decky/legendary path resolution + config isolation
  core_service      — wraps legendary's LegendaryCore (auth, metadata, library)
  download_service  — drives DLManager and emits progress events
  launch_service    — cloud-save-around-launch orchestration
  saves_service     — sync-saves wrapper + conflict handling
  proton / prefix   — Proton discovery and per-game compatdata prefixes
  steam_reviews     — Steam review-score resolution + local cache
  settings_store    — persisted plugin settings
"""
