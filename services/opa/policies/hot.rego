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


# deny["fee too high"] if {
#     input.fee_sats > data.hot.limits.max_fee_sats
# }

# deny["fee per sat too high"] if {
#     input.fee_sats > data.hot.limits.max_fee_sats
# }

#vbytes contraint?

# deny["too many inputs"] if {
#     input.inputs_count > data.hot.limits.max_inputs
# }

# deny["missing changepos"] if {
#     input.changepos == -1
#     not data.hot.allow_no_change
# }