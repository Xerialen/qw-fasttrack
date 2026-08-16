"""Obligatoriska evidensfält per atgardsklass — verktygslada/taxonomi/4."""
from __future__ import annotations

KLASSER = (
    "kriterium_mal",
    "carve_origin",
    "slapp_lank",
    "lagg_lank",
    "pris_vreq",
    "styre_sjband",
    "starttillstand_alofte",
    "ignorera_avsett",
    "okand_ingen_fix",
)

UNKNOWN_REASONS = (
    "missing_graph_inventory",
    "missing_harness_predicate",
    "missing_plan_fields",
    "regime_or_population_conflict",
    "classifier_disagreement",
)

REASON_PRIO = (
    "missing_graph_inventory",
    "missing_harness_predicate",
    "missing_plan_fields",
    "regime_or_population_conflict",
    "classifier_disagreement",
)

# Stigar relativt evidens. Tom/unknown/null = saknas.
# styre/pris: hela controllersekvensen (rev 4).
CONTROLLER = (
    "controllersekvens.takeoff_cell",
    "controllersekvens.runway",
    "controllersekvens.runway_measured",
    "controllersekvens.sj_progress",
    "controllersekvens.sj_progress_measured",
    "controllersekvens.phase",
    "controllersekvens.phase_prev",
    "controllersekvens.on_ground",
    "controllersekvens.jump_cmd",
    "controllersekvens.first_air_vz",
    "controllersekvens.first_air_vz_measured",
)

# (path, reason_om_saknas)
KRAV: dict[str, tuple[tuple[str, str], ...]] = {
    "kriterium_mal": (
        ("falt.predikat", "missing_harness_predicate"),
        ("falt.ben", "missing_plan_fields"),
    ),
    "carve_origin": (
        ("falt.cell", "missing_graph_inventory"),
        ("falt.verdict", "missing_graph_inventory"),
        ("falt.cell_origin", "missing_graph_inventory"),
    ),
    "slapp_lank": (
        ("falt.selected_link", "missing_plan_fields"),
        ("falt.kind", "missing_plan_fields"),
        ("falt.motexempel_lank", "missing_plan_fields"),
    ),
    "lagg_lank": (
        ("falt.foreslagen_kant", "missing_graph_inventory"),
    ),
    "pris_vreq": tuple(
        (p, "missing_plan_fields") for p in CONTROLLER
    ) + (
        ("falt.selected_link", "missing_plan_fields"),
        ("falt.alt_link", "missing_plan_fields"),
        ("falt.v_req", "missing_plan_fields"),
        ("falt.speed", "missing_plan_fields"),
        ("falt.p_base", "missing_plan_fields"),
        ("falt.p_total", "missing_plan_fields"),
        ("falt.plan_fail", "missing_plan_fields"),
        ("mekanikbelagg.oberoende_av_vreq", "missing_plan_fields"),
        ("mekanikbelagg.lank", "missing_plan_fields"),
        ("mekanikbelagg.forsok_id", "missing_plan_fields"),
        ("mekanikbelagg.lufttick_t", "missing_plan_fields"),
    ),
    "styre_sjband": tuple((p, "missing_plan_fields") for p in CONTROLLER),
    "starttillstand_alofte": (
        ("falt.regim", "regime_or_population_conflict"),
        ("falt.start", "regime_or_population_conflict"),
    ),
    "ignorera_avsett": (),
    "okand_ingen_fix": (),
}

# Klasser som kräver minst en pekare {fil, falt|rad} i kandidatens kallor.
KRAV_PEKARE = frozenset(k for k in KLASSER if k != "okand_ingen_fix")

PRIS_OCERTIFIERAD = True
