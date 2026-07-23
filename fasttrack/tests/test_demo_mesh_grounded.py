from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from demo_mesh import extract, grounded_mask, load_samples_jsonl  # noqa: E402


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

    def test_authoritative_single_frame_rim_contact_splits_chain_jump(self):
        dt = 0.013
        rows = []

        def add(index, x, z, speed, on_ground):
            rows.append({
                "t": round(index * dt, 3),
                "ent": 7,
                "origin": [float(x), 0.0, float(z)],
                "vel": [float(speed), 0.0, 0.0],
                "on_ground": on_ground,
                "ground_ent": 0 if on_ground else -1,
            })

        for index in range(10):
            add(index, 0, 0, 320, True)
        for offset, z in enumerate((12, 22, 30, 36, 40, 42, 40, 36, 30, 22, 12, 6), 10):
            add(offset, (offset - 9) * (100 / 13), z, 400, False)
        add(22, 100, 0, 450, True)  # the only 13 ms rim-contact sample
        for offset, z in enumerate((12, 22, 30, 36, 40, 42, 40, 36, 30, 22, 12, 6), 23):
            add(offset, 100 + (offset - 22) * (120 / 13), z, 480, False)
        for index in range(35, 45):
            add(index, 220, 0, 0, True)

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "chain-jump.jsonl"
            path.write_text(
                "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
                encoding="utf-8",
            )
            samples, authoritative = load_samples_jsonl(path, ent=7)

        masked = extract(samples, authoritative_mask=authoritative)
        heuristic = extract(samples)
        self.assertEqual(len(masked["jumps"]), 2)
        self.assertEqual([jump["speed_median"] for jump in masked["jumps"]], [320.0, 450.0])
        self.assertEqual(len(heuristic["jumps"]), 1)


if __name__ == "__main__":
    unittest.main()
