package policy.hot

default allow := false

allow {
  input_valid
  not deny[_]
}

decision := {
  "allow": allow,
  reasons: deny,
  "limits": limits
}

limits := data.hot.limits

input_valid {
  input.amount_sats > 0
  input.target_address != ""
  input.request_id != ""
  input.network != ""
}

deny["network not allowed"] {
  not data.networks.allowed[input.network]
}

deny["amount exceeds limit"] {
  input.amount_sats > data.hot.limits.max_amount_sats
}

deny["target not whitelisted"] {
  not data.hot.whitelist_addresses[_] == input.target_address
}

#Später extra authentifizierung? hex code im meta?
deny["tag required"] {
  data.hot.require_tag == true
  not input.meta.tag
}