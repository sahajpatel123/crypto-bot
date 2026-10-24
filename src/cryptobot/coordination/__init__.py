"""Coordination interfaces (manager-owned)."""
from .coordinator import Coordinator, CoordinatorDecision
from .decision_record import DecisionRecord, FeatureEvidence
from .exits import ExitPolicy, decode_exit_rule, encode_exit_rule
from .intent import DataQuality, ForecastCost, Intent, Side
from .risk_outcomes import RiskOutcomeSink
from .selector import Candidate, Selector, SelectorConfig, SelectorDecision

__all__ = ["Intent", "DataQuality", "ForecastCost", "Side", "Coordinator", "CoordinatorDecision",
           "DecisionRecord", "FeatureEvidence", "RiskOutcomeSink",
           "ExitPolicy", "encode_exit_rule", "decode_exit_rule",
           "Candidate", "Selector", "SelectorConfig", "SelectorDecision"]
