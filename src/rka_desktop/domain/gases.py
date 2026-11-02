"""Gas catalogue and experiment-type rules.

The rig mixes gases through one MFC per gas type. Which gases exist on a given machine is a
configuration fact (the MFC channel list); which gases an experiment may use is a business
rule decided here:

* every experiment uses exactly one inert gas (N2 or Ar) for carrier, purge and safe disposal;
* a reduction experiment may additionally use CO / CO2 / H2 / CH4;
* an oxidation experiment may additionally use CO2 / O2.

Everything else stays at zero in recipes and in manual gas set-points.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class GasInfo:
    key: str  # upper-case identifier used in config and storage, e.g. "CO2"
    label: str  # display label with subscript digits
    hazard: str  # short hazard note shown next to the gas
    inert: bool
    column: str  # storage column / payload key, e.g. "co2_lpm"


GASES: tuple[GasInfo, ...] = (
    GasInfo("N2", "N₂", "惰性", True, "n2_lpm"),
    GasInfo("AR", "Ar", "惰性", True, "ar_lpm"),
    GasInfo("H2", "H₂", "易燃", False, "h2_lpm"),
    GasInfo("CO", "CO", "有毒 / 可燃", False, "co_lpm"),
    GasInfo("CO2", "CO₂", "", False, "co2_lpm"),
    GasInfo("CH4", "CH₄", "易燃", False, "ch4_lpm"),
    GasInfo("O2", "O₂", "助燃", False, "o2_lpm"),
)
GAS_KEYS: tuple[str, ...] = tuple(gas.key for gas in GASES)
GAS_BY_KEY: dict[str, GasInfo] = {gas.key: gas for gas in GASES}
GAS_COLUMNS: tuple[str, ...] = tuple(gas.column for gas in GASES)
INERT_GASES: tuple[str, ...] = tuple(gas.key for gas in GASES if gas.inert)


class ExperimentType(str, Enum):
    REDUCTION = "reduction"
    OXIDATION = "oxidation"


EXPERIMENT_TYPE_LABELS = {ExperimentType.REDUCTION: "还原实验", ExperimentType.OXIDATION: "氧化实验"}

PROCESS_GASES: dict[ExperimentType, tuple[str, ...]] = {
    ExperimentType.REDUCTION: ("CO", "CO2", "H2", "CH4"),
    ExperimentType.OXIDATION: ("CO2", "O2"),
}


class GasRuleError(ValueError):
    pass


def parse_experiment_type(value: object) -> ExperimentType:
    try:
        return ExperimentType(str(value))
    except ValueError as exc:
        raise GasRuleError("实验类型只能是 reduction（还原）或 oxidation（氧化）") from exc


def parse_inert_gas(value: object) -> str:
    key = str(value or "").upper()
    if key not in INERT_GASES:
        raise GasRuleError("惰性气只能是 N2 或 AR")
    return key


def normalise_gas_key(value: object) -> str | None:
    key = str(value or "").strip().upper()
    return key if key in GAS_BY_KEY else None


def allowed_gases(experiment_type: ExperimentType, inert_gas: str) -> tuple[str, ...]:
    """Gases that may carry a non-zero flow in an experiment of this type."""
    return (inert_gas, *PROCESS_GASES[experiment_type])


def label(key: str) -> str:
    info = GAS_BY_KEY.get(key)
    return info.label if info else key


def format_flows(flows: dict[str, float], *, skip_zero: bool = True) -> str:
    parts = [f"{label(key)} {value:.2f}" for key, value in flows.items() if not (skip_zero and value <= 0)]
    return " / ".join(parts) if parts else "全部关闭"


def zero_flows() -> dict[str, float]:
    return {key: 0.0 for key in GAS_KEYS}
