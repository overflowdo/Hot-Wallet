package hot.limits

import rego.v1

#Load data
balance := input.balance

default action := "hold"
default amount := 0
default risk_score := 0
default reason := "within_limits"


min := data.hot.balance.min
max := data.hot.balance.max

target := (min + max) / 2

deviation := balance - target


############
#risk score
#normalisierte Abweichung vom optimalen Bereich
# Abstand nach oben (Exposure Risk)
range_half := (max - min) / 2

risk_score := round((abs(deviation) / range_half) * 100)


#################
#check action
action := "hot_to_cold" if {
    balance > max
}

action := "cold_to_hot" if {
    balance < min
}

action := "hold" if {
    balance >= min
    balance <= max
}


###############
#create differnece
amount := balance - target if {
    action == "hot_to_cold"
}

amount := target - balance if {
    action == "cold_to_hot"
}

amount := 0 if {
    action == "hold"
}

##################
execution := {
    "confirmation_blocks": confirmation_blocks,
    "estimate_mode": estimate_mode
}

confirmation_blocks := 1 if {
    risk_score > 70
}

confirmation_blocks := 2 if {
    risk_score > 30
    risk_score <= 70
}

confirmation_blocks := 6 if {
    risk_score <= 30
}

estimate_mode := "conservative" if {
    risk_score > 30
}

estimate_mode := "economical" if {
    risk_score <= 30
}


###################
reason := "above_max" if {
    action == "hot_to_cold"
}

reason := "below_min" if {
    action == "cold_to_hot"
}

reason := "within_limits" if {
    action == "hold"
}



output := {
    "action": action,
    "balance": balance,
    "target": target,
    "amount": amount,
    "risk_score": risk_score,
    "reason": reason,
    "execution": execution
}