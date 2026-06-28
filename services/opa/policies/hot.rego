package policy.hot

import rego.v1

default allow := false

allow if{
  count(deny) == 0
}

decision := {
  "allow": allow,
  "reasons": deny,
  "limits": limits
}

limits := data.hot.limits

#Rail OPA überprüfen
skip_amount_fee_checks if {
    object.get(input, "rail", "") == "OPA"
}

#Input validation

deny["missing psbt_id"] if {
    object.get(input, "psbt_id", "") == ""
}

deny["missing wallet_type"] if {
    object.get(input, "wallet_type", "") == ""
}

deny["missing psbt"] if {
    object.get(input, "psbt", "") == ""
}

deny["missing source address"] if {
    object.get(input, "source_address", "") == ""
}

deny["missing target address"] if {
    object.get(input, "target_address", "") == ""
}

deny["missing network"] if {
    object.get(input, "network", "") == ""
}

deny["invalid amount"] if {
    object.get(input, "amount_sats", 0) <= 0
}

deny["network not allowed"] if{
    not data.networks.allowed[input.network]
}

deny["amount exceeds limit"] if{
    not skip_amount_fee_checks
    input.amount_sats > data.hot.limits.max_amount_sats
}

#Später extra authentifizierung? hex code im meta?
deny["tag required"] if{
    data.hot.require_tag == true
    not input.meta.tag
}

deny["missing psbt hash"] if {
    data.hot.require_sha256
    input.sha256 == ""
}

deny["fee exceeds limit"] if {
    not skip_amount_fee_checks
    input.fee_sats != null
    input.fee_sats > data.hot.limits.max_fee_sats
}

deny["fee rate exceeds limit"] if {
    not skip_amount_fee_checks
    input.fee_rate != null
    input.fee_rate > data.hot.limits.max_fee_rate_sat_vb
}

deny["fee rate below minimum"] if {
    not skip_amount_fee_checks
    input.fee_rate != null
    input.fee_rate < data.hot.limits.min_fee_rate_sat_vb
}