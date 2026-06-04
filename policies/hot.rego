package policy.hot

# Output shape:
# {
#   "allow": <bool>,
#   "reasons": [ ... ],
#   "limits": { ... }
# }

default allow := false

reasons := {r |
  r := deny[_]
}

# -------------------------------------------------------------------
# ALLOW (Hot auto-sign)
# -------------------------------------------------------------------
allow {
  valid_input
  not deny[_]
}

# -------------------------------------------------------------------
# DENY rules
# -------------------------------------------------------------------

# Require basic fields
deny["missing required fields"] {
  not valid_input
}

valid_input {
  input.amount_sats > 0
  input.target_address != ""
  input.request_id != ""
  input.tx_hash != ""
  input.actor == "middleware"
  input.network != ""
}

# Network must be allowed
deny["network not allowed"] {
  not data.networks.allowed[input.network]
}

# Target must be whitelisted (for auto hot flow)
deny["target address not whitelisted"] {
  not address_whitelisted
}

address_whitelisted {
  some a
  a := data.hot.whitelist_addresses[_]
  a == input.target_address
}

# Amount must be within max
deny["amount exceeds hot max"] {
  input.amount_sats > data.hot.limits.max_amount_sats
}

# Optional: require a tag (simple governance)
deny["missing tag"] {
  data.hot.require_tag == true
  not input.meta.tag
}

# Velocity control: deny if daily spent exceeds limit
# Middleware must supply:
#   input.velocity.day_spent_sats
deny["daily velocity limit exceeded"] {
  input.velocity.day_spent_sats + input.amount_sats > data.hot.limits.daily_spent_sats
}

# Optional: restrict to specific purpose/reason values
deny["reason not allowed"] {
  data.hot.allowed_reasons != null
  not reason_allowed
}

reason_allowed {
  some r
  r := data.hot.allowed_reasons[_]
  r == input.reason
}

# -------------------------------------------------------------------
# Useful output fields
# -------------------------------------------------------------------
limits := {
  "max_amount_sats": data.hot.limits.max_amount_sats,
  "daily_spent_sats": data.hot.limits.daily_spent_sats
}