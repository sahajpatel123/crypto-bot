"""Coordination interfaces (manager-owned)."""
from .intent import Intent, DataQuality, ForecastCost, Side
from .coordinator import Coordinator, CoordinatorDecision
from .decision_record import DecisionRecord, FeatureEvidence
from .risk_outcomes import RiskOutcomeSink
from .exits import ExitPolicy, encode_exit_rule, decode_exit_rule
from .selector import Candidate, Selector, SelectorConfig, SelectorDecision

__all__ = ["Intent", "DataQuality", "ForecastCost", "Side", "Coordinator", "CoordinatorDecision",
           "DecisionRecord", "FeatureEvidence", "RiskOutcomeSink",
           "ExitPolicy", "encode_exit_rule", "decode_exit_rule",
           "Candidate", "Selector", "SelectorConfig", "SelectorDecision"]
