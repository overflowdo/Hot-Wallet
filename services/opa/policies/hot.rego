package policy.hot

import rego.v1

default allow := false

allow if{
  input_valid
  count(deny) == 0
}

decision := {
  "allow": allow,
  "reasons": deny,
  "limits": limits
}

limits := data.hot.limits

input_valid if{
  input.amount_sats > 0
  input.target_address != ""
  input.request_id != ""
  input.network != ""
}

deny["network not allowed"] if{
  not data.networks.allowed[input.network]
}

deny["amount exceeds limit"] if{
  input.amount_sats > data.hot.limits.max_amount_sats
}

deny["target not whitelisted"] if{
  not input.target_address in data.hot.whitelist_addresses
}

#Später extra authentifizierung? hex code im meta?
deny["tag required"] if{
  data.hot.require_tag == true
  not input.meta.tag
}