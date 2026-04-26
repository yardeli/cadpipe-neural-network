"""Vehicle geometry abstraction — parameterizes everything currently
hardcoded for RAM-C.

Designed as the integration point for an upstream "drop a CAD file in"
pipeline (S-8). The CAD parser extracts these fields from STEP/IGES;
the rest of the framework consumes them via VehicleGeometry.

Usage:
    from plasmanet.mechanism_search.geometry import VehicleGeometry, RAM_C_GEOMETRY

    # Predefined: RAM-C
    geom = RAM_C_GEOMETRY

    # Custom (from a designer):
    geom = VehicleGeometry(
        name="my_hgv",
        body_length_m=4.0,
        nose_radius_m=0.05,
        body_type='sphere_cone',
        half_angle_deg=8.0,
        reflectometer_stations_zL=[0.20, 0.50, 0.80],
        sheath_thickness_m=0.04,
    )

    # Future (S-8): from CAD
    # geom = VehicleGeometry.from_step_file('my_design.step')
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable


@dataclass
class VehicleGeometry:
    """All vehicle-specific parameters needed by the search framework.

    This abstraction is the single source of truth for "what shape is the
    vehicle and where do we measure plasma." The CFD-output evaluator,
    Cantera 0D evaluator, and PlasmaNet surrogate all consume this — none
    hardcode geometry constants.
    """

    name: str
    """Identifier for logs / output dirs (e.g., 'ram_c', 'apollo_cm', 'my_hgv')."""

    body_length_m: float
    """Total axial length of the vehicle (nose-to-base)."""

    nose_radius_m: float
    """Spherical nose radius. For pointed bodies, set to a small value (e.g., 0.001)."""

    body_type: str = "sphere_cone"
    """One of 'sphere_cone', 'capsule', 'wedge', 'cylinder', or 'custom'.
    Used by body_radius_at_x() to compute wall offset."""

    half_angle_deg: float = 9.0
    """Cone half-angle for sphere-cone bodies. Ignored for other types."""

    base_radius_m: Optional[float] = None
    """Base radius (used by capsule/cylinder body types). Auto-derived from
    body_length + half_angle for sphere-cone."""

    reflectometer_stations_zL: list[float] = field(
        default_factory=lambda: [0.14, 0.32, 0.48, 0.67, 0.88]
    )
    """Axial fractions z/L where on-body sensors are located. RAM-C
    reflectometer geometry by default. New vehicles override."""

    sheath_thickness_m: float = 0.3
    """Radial thickness of the sheath shell to integrate over. ~0.3m for
    re-entry capsules with detached bow shock; smaller (~0.05m) for slender
    hypersonic glide vehicles."""

    # Custom radius function (used when body_type='custom', e.g., from CAD)
    custom_radius_fn: Optional[Callable[[float], float]] = None

    def body_radius_at_x(self, x_m: float) -> float:
        """Wall radius at axial position x (nose at x=0).

        Used by both CFD post-processing (sheath shell extraction) and
        Cantera 0D estimates (sheath path-length for dB attenuation).
        """
        if x_m <= 0:
            return 0.0
        if x_m >= self.body_length_m:
            return self.base_radius_m or self._derive_base_radius()

        if self.body_type == "sphere_cone":
            half = math.radians(self.half_angle_deg)
            R_n = self.nose_radius_m
            x_tang = R_n * (1 - math.sin(half))
            if x_m <= x_tang:
                return math.sqrt(max(R_n * R_n - (R_n - x_m) ** 2, 0.0))
            r_tang = R_n * math.cos(half)
            return r_tang + (x_m - x_tang) * math.tan(half)
        elif self.body_type == "cylinder":
            return self.base_radius_m or self.nose_radius_m
        elif self.body_type == "capsule":
            # Spherical front + cylindrical aft (Apollo-like)
            R_n = self.nose_radius_m
            base_r = self.base_radius_m or 0.5 * self.body_length_m
            if x_m <= R_n:
                return math.sqrt(max(R_n * R_n - (R_n - x_m) ** 2, 0.0))
            return base_r
        elif self.body_type == "wedge":
            half = math.radians(self.half_angle_deg)
            return x_m * math.tan(half)
        elif self.body_type == "custom":
            if self.custom_radius_fn is None:
                raise ValueError(
                    f"VehicleGeometry '{self.name}' has body_type='custom' "
                    f"but no custom_radius_fn set."
                )
            return self.custom_radius_fn(x_m)
        else:
            raise ValueError(f"Unknown body_type: {self.body_type}")

    def _derive_base_radius(self) -> float:
        """Compute base radius for sphere-cone from length + half angle."""
        if self.body_type == "sphere_cone":
            R_n = self.nose_radius_m
            half = math.radians(self.half_angle_deg)
            x_tang = R_n * (1 - math.sin(half))
            r_tang = R_n * math.cos(half)
            return r_tang + (self.body_length_m - x_tang) * math.tan(half)
        return self.base_radius_m or self.nose_radius_m

    def estimate_sheath_path_length(self, x_m: float) -> float:
        """Estimate plasma-sheath thickness at axial position x.

        Used by Cantera 0D's dB attenuation estimate. Default: half the
        bow-shock standoff distance. Refined estimates can override.
        """
        # Bow-shock standoff scaling: delta_s / R_n ≈ 0.78 * (rho_inf/rho_post)
        # For strong shocks, rho_post/rho_inf ≈ 6, so delta_s ≈ 0.13 R_n.
        # Sheath is somewhat thicker than the standoff (turbulent + chemistry).
        R_n = self.nose_radius_m
        return 0.13 * R_n + self.sheath_thickness_m * 0.3

    @classmethod
    def from_step_file(cls, step_path: Path) -> "VehicleGeometry":
        """Future entry point (S-8): extract geometry from a CAD STEP file.

        Not yet implemented — placeholder for the "drop a CAD file in"
        pipeline. The implementation will use FreeCAD or pythonocc-core to
        parse STEP, identify the body axis, measure length/nose radius, and
        infer body type from surface curvature.
        """
        raise NotImplementedError(
            "S-8 task: STEP-file → VehicleGeometry parser not yet implemented. "
            "For now, instantiate VehicleGeometry directly with measured "
            "parameters."
        )


# ──────────────────────────────────────────────────────────────────────────────
# Predefined geometries (extend as you add vehicles)
# ──────────────────────────────────────────────────────────────────────────────

RAM_C_GEOMETRY = VehicleGeometry(
    name="ram_c",
    body_length_m=2.54,
    nose_radius_m=0.1524,
    body_type="sphere_cone",
    half_angle_deg=9.0,
    # The 5 reflectometer stations Jones & Cross 1972 used
    reflectometer_stations_zL=[0.14, 0.32, 0.48, 0.67, 0.88],
    sheath_thickness_m=0.30,
)

APOLLO_CM_GEOMETRY = VehicleGeometry(
    name="apollo_cm",
    body_length_m=3.40,         # Apollo CM length
    nose_radius_m=4.69,         # large heat shield radius
    body_type="capsule",
    base_radius_m=1.96,
    reflectometer_stations_zL=[0.20, 0.50, 0.80],   # not measured, placeholder
    sheath_thickness_m=0.50,
)

FIRE_II_GEOMETRY = VehicleGeometry(
    name="fire_ii",
    body_length_m=0.67,
    nose_radius_m=0.935,        # FIRE II spherical front
    body_type="capsule",
    base_radius_m=0.335,
    reflectometer_stations_zL=[0.30, 0.60, 0.90],
    sheath_thickness_m=0.20,
)

# Generic slender HGV (illustrative, not a specific vehicle)
GENERIC_HGV_GEOMETRY = VehicleGeometry(
    name="generic_hgv",
    body_length_m=5.0,
    nose_radius_m=0.025,        # sharp nose for low drag
    body_type="sphere_cone",
    half_angle_deg=4.0,
    reflectometer_stations_zL=[0.20, 0.50, 0.80],
    sheath_thickness_m=0.05,    # thin, attached shock
)


PREDEFINED_GEOMETRIES: dict[str, VehicleGeometry] = {
    "ram_c": RAM_C_GEOMETRY,
    "apollo_cm": APOLLO_CM_GEOMETRY,
    "fire_ii": FIRE_II_GEOMETRY,
    "generic_hgv": GENERIC_HGV_GEOMETRY,
}


def get_geometry(name: str) -> VehicleGeometry:
    """Lookup a predefined VehicleGeometry by name."""
    if name not in PREDEFINED_GEOMETRIES:
        raise KeyError(
            f"No predefined geometry '{name}'. "
            f"Available: {list(PREDEFINED_GEOMETRIES.keys())}. "
            f"Or instantiate VehicleGeometry() directly."
        )
    return PREDEFINED_GEOMETRIES[name]
