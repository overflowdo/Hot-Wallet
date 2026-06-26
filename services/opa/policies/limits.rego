package hot.limits

import data.limits

#Load data
balance := input.balance

default action := "hold"
default amount := 0
default risk_score := 0
default reason := "within_limits"


min := limits.hot.min
max := limits.hot.max

target := (min + max) / 2

deviation := balance - target


############
#risk score
#normalisierte Abweichung vom optimalen Bereich
# Abstand nach oben (Exposure Risk)
range_half := (max - min) / 2

risk_score := int(clamp(0, 100,
    (abs(deviation) / range_half) * 100
))


#################
#check action
action := "hot_to_cold" {
    balance > max
}

action := "cold_to_hot" {
    balance < min
}

action := "hold" {
    balance >= min
    balance <= max
}


###############
#create differnece
amount := balance - target {
    action == "hot_to_cold"
}

amount := target - balance {
    action == "cold_to_hot"
}

amount := 0 {
    action == "hold"
}

##################
execution := {
    "confirmation_blocks": confirmation_blocks,
    "estimate_mode": estimate_mode
}

confirmation_blocks := 1 {
    risk_score > 70
}

confirmation_blocks := 2 {
    risk_score > 30
    risk_score <= 70
}

confirmation_blocks := 6 {
    risk_score <= 30
}

estimate_mode := "conservative" {
    risk_score > 30
}

estimate_mode := "economical" {
    risk_score <= 30
}


###################
reason := "above_max" {
    action == "hot_to_cold"
}

reason := "below_min" {
    action == "cold_to_hot"
}

reason := "within_limits" {
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