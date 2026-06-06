#This file contains the business logic to validate the defined rules against the sent intent

package policy.hot

default allow := false

# -------------------------
# Main rule
# -------------------------
allow {
  input_valid
  not deny[_]
}

# -------------------------
# Reasons output
# -------------------------
reasons := {r |
  r := deny[_]
}

limits := {
  "max_amount_sats": data.hot.limits.max_amount_sats,
  "daily_spent_sats": data.hot.limits.daily_spent_sats
}

# -------------------------
# Input validation
# -------------------------
input_valid {
  input.amount_sats > 0
  input.target_address != ""
  input.request_id != ""
  input.network != ""
  input.actor == "middleware"
}

# -------------------------
# Deny rules
# -------------------------
deny["network not allowed"] {
  not data.networks.allowed[input.network]
}

deny["amount exceeds limit"] {
  input.amount_sats > data.hot.limits.max_amount_sats
}

deny["missing tag"] {
  data.hot.require_tag == true
  not input.meta.tag
}

deny["target not whitelisted"] {
  not input.target_address in data.hot.whitelist_addresses
}

deny["invalid reason"] {
  data.hot.allowed_reasons != null
  not input.reason in data.hot.allowed_reasons
}

deny["fee too high"] {
  input.fee_rate_sat_vb > data.hot.limits.max_fee_rate_sat_vb
}

output := {
  "allow": allow,
  "reasons": reasons,
  "limits": limits
}