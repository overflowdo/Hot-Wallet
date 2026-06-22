package policy.hot

import rego.v1

default allow := false

allow if {
    input_valid
    count(deny) == 0
}

decision := {
    "allow": allow,
    "reasons": deny,
    "limits": limits
}

limits := data.hot.limits

################################################################################
# Input validation
################################################################################

input_valid if {
    input.amount_sats > 0
    input.psbt_id != ""
    input.psbt != ""
    input.source_address != ""
    input.target_address != ""
    input.network != ""
    input.fee != ""
    input.network != ""
}

################################################################################
# Deny rules
################################################################################

deny["network not allowed"] if {
    not data.networks.allowed[input.network]
}

deny["amount exceeds limit"] if {
    input.amount_sats > data.hot.limits.max_amount_sats
}

################################################################################
# Fee checks
################################################################################

deny["fee exceeds limit"] if {
    input.fee_sats != null
    input.fee_sats > data.hot.limits.max_fee_sats
}

deny["fee rate exceeds limit"] if {
    input.fee_rate != null
    input.fee_rate > data.hot.limits.max_fee_rate_sat_vb
}

deny["fee rate below minimum"] if {
    input.fee_rate != null
    input.fee_rate < data.hot.limits.min_fee_rate_sat_vb
}

################################################################################
# Optional SHA256 integrity
################################################################################

deny["missing psbt hash"] if {
    data.hot.require_sha256
    input.sha256 == ""
}

################################################################################
# Optional tag
################################################################################

deny["tag required"] if {
    data.hot.require_tag
    not input.meta.tag
}