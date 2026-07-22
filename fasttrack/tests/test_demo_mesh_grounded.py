from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from demo_mesh import grounded_mask  # noqa: E402


def jump_samples(fps: float = 72.0) -> tuple[list[tuple], range, range, range]:
    """One second of floor, a QW jump, then one second of floor."""
    dt = 1.0 / fps
    floor_z = 56.0
    samples: list[tuple] = []

    plateau_before = range(0, int(fps))
    for i in plateau_before:
        samples.append((i * dt, 0.0, 0.0, floor_z, 0.0))

    takeoff_t = samples[-1][0]
    air_start = len(samples)
    k = 1
    while True:
        tau = k * dt
        z = floor_z + 270.0 * tau - 0.5 * 800.0 * tau * tau
        if z <= floor_z:
            break
        # Quake network coordinates are quantized to eighth units. Around
        # the apex that quantization creates a short, deceptively flat cap.
        z = round(z * 8.0) / 8.0
        samples.append((takeoff_t + tau, 0.0, 0.0, z, 0.0))
        k += 1
    airborne = range(air_start, len(samples))

    landing_t = takeoff_t + k * dt
    after_start = len(samples)
    for i in range(int(fps)):
        samples.append((landing_t + i * dt, 0.0, 0.0, floor_z, 0.0))
    plateau_after = range(after_start, len(samples))
    return samples, plateau_before, airborne, plateau_after


class GroundedMaskTests(unittest.TestCase):
    def test_time_window_rejects_every_air_sample_and_preserves_plateau_edges(self):
        for fps in (72.0, 77.0, 144.0):
            with self.subTest(fps=fps):
                samples, before, airborne, after = jump_samples(fps)
                mask = grounded_mask(samples)

                self.assertTrue(all(mask[i] for i in list(before)[1:]))
                self.assertTrue(mask[before.stop - 1], "last sample before takeoff")
                self.assertTrue(mask[after.start], "first sample after landing")
                self.assertTrue(all(mask[i] for i in list(after)[:-1]))
                self.assertTrue(airborne, "fixture must contain an airborne arc")
                self.assertTrue(all(not mask[i] for i in airborne))

    def test_quantized_qwd_apex_cannot_use_a_window_that_turns_mid_side(self):
        z_values = [
            87.625, 89.375, 91.0, 92.5, 93.75, 95.0, 96.125,
            97.0, 97.875, 98.5, 99.0, 99.5, 99.75, 99.875,
            99.875, 99.75, 99.375, 99.0, 98.5, 97.75, 97.0,
            96.0, 94.875, 93.75, 92.375, 90.875, 89.375, 87.625,
        ]
        dt = 1.0 / 77.0
        samples = [
            (i * dt, float(i), 0.0, z, 400.0)
            for i, z in enumerate(z_values)
        ]
        self.assertTrue(all(not value for value in grounded_mask(samples)))

    def test_isolated_sample_is_not_ground(self):
        self.assertEqual(grounded_mask([(0.0, 0.0, 0.0, 56.0, 0.0)]), [False])


if __name__ == "__main__":
    unittest.main()
