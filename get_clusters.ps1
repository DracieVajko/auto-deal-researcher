$clusters = "browser-security","authorization-consistency","package-hygiene","dependency-health","naming-tests","abstraction-fitness","ai-generated-debt","cli-api-contracts","convention-outlier","cross-module-arch","design-coherence","error-observability","incomplete-migration","init-coupling","logic-clarity","low-level-elegance","high-level-elegance","mid-level-elegance","search-types-contracts","storage-watchlist","agents-notifications-types","diamond"
foreach ($c in $clusters) {
  Write-Output "===== CLUSTER: $c ====="
  python -m desloppify plan cluster show $c 2>&1
}
