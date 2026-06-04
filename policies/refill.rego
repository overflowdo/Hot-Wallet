package policy.refillpackage# Output shape:
# {
#   "allow_intent": <bool>,
#   "recommended_amount_sats": <int>,
#   "notify_human": <bool>,
#   "reasons": [ ... ]
# }

default allow_intent := false

notify_human := true

reasons := {r |
  r := deny[_]
}

allow_intent {
  valid_input
  not deny[_]
}

# -------------------------------------------------------------------
# Input validation
# -------------------------------------------------------------------
deny["missing required fields"] {
  not valid_input
}

valid_input {
  input.network != ""
  input.hot_balance_sats >= 0
  input.thresholds.min_hot_sats > 0
  input.thresholds.target_hot_sats >= input.thresholds.min_hot_sats
  input.actor == "tx-builder"  # or "middleware" - pick one and stay consistent
}

# Network must be allowed
deny["network not allowed"] {
  not data.networks.allowed[input.network]
}

# Trigger condition: only if below min threshold
deny["hot balance not below min threshold"] {
  input.hot_balance_sats >= input.thresholds.min_hot_sats
}

# Cooldown / anti-spam: require that last refill was long enough ago
# Middleware/Builder supplies input.last_refill_age_seconds
deny["refill cooldown not elapsed"] {
  data.refill.cooldown_seconds > 0
  input.last_refill_age_seconds < data.refill.cooldown_seconds
}

# Max refill amount guardrail (safety)
deny["recommended refill would exceed max"] {
  recommended_amount_sats > data.refill.limits.max_refill_sats
}

# -------------------------------------------------------------------
# Recommendation logic (pure function-like rules)
# recommended = target - current, clamped by min/max
# -------------------------------------------------------------------
recommended_amount_sats := rec {
  base := input.thresholds.target_hot_sats - input.hot_balance_sats
  base > 0
  rec := clamp(base, data.refill.limits.min_refill_sats, data.refill.limits.max_refill_sats)
} else := 0

clamp(x, lo, hi) := y {
  x < lo
  y := lo
} else := y {
  x > hi
  y := hi
} else := y {
  y := x
}