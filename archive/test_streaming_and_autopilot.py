"""Unit tests for Real-Time Streaming Perception, Spinal Autopilot, and Executive Cortex."""

from __future__ import annotations

import time
import unittest
import numpy as np

from reticle.sensory.streaming_transducer import (
    StreamingROIFilter,
    StreamingVideoTransducer,
    SensoryEvent
)
from reticle.adapters.minecraft_adapter import (
    SimulatedMinecraftEnvironment,
    MinecraftAdapter
)
from reticle.minecraft.autopilot import (
    SpinalCordAutopilot,
    AutopilotStatus
)
from reticle.minecraft.executive_cortex import ExecutiveCortex


class StreamingAndAutopilotTests(unittest.TestCase):

    def test_streaming_roi_filter_instant_transient_detection(self):
        transducer = StreamingVideoTransducer()
        # Monitor a 100x100 minimap in the top-right corner of a 720p frame
        transducer.register_roi("minimap", (1180, 0, 1280, 100), alpha=0.1, z_threshold=3.0)

        # Baseline: 20 frames of static terrain with slight subtle sensor noise
        for idx in range(20):
            frame = np.ones((720, 1280, 3), dtype=np.uint8) * 80
            # Add subtle jitter
            frame[0:100, 1180:1280] += np.random.randint(-1, 2, (100, 100, 3), dtype=np.int16).clip(0, 255).astype(np.uint8)
            events = transducer.process_frame(frame, timestamp_ms=idx * 33.3)
            self.assertEqual(len(events), 0, f"False positive detected at baseline frame {idx}")

        # Frame 21: Sudden high-contrast icon appears in minimap (e.g. enemy ping / death icon)
        flash_frame = np.ones((720, 1280, 3), dtype=np.uint8) * 80
        flash_frame[30:70, 1210:1250] = [0, 0, 255]  # Bright red 40x40 icon
        events = transducer.process_frame(flash_frame, timestamp_ms=21 * 33.3)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "TRANSIENT_SPIKE")
        self.assertEqual(events[0].channel, "minimap")
        self.assertGreater(events[0].metadata["z_score"], 3.0)

    def test_streaming_per_frame_performance_budget(self):
        transducer = StreamingVideoTransducer()
        transducer.register_roi("minimap", (1000, 0, 1200, 200))
        transducer.register_roi("health_bar", (100, 600, 300, 650))
        transducer.register_roi("crosshairs", (620, 340, 660, 380))

        frame = np.zeros((720, 1280, 3), dtype=np.uint8)

        # Warmup
        for _ in range(5):
            transducer.process_frame(frame)

        # Measure 50 frames
        t0 = time.perf_counter()
        for _ in range(50):
            transducer.process_frame(frame)
        duration_s = time.perf_counter() - t0
        ms_per_frame = (duration_s / 50.0) * 1000.0

        # Must comfortably beat the 16.6ms 60 FPS budget (< 2.0ms per frame)
        self.assertLess(ms_per_frame, 3.0, f"Per-frame cost {ms_per_frame:.2f}ms exceeds target budget")

    def test_spinal_cord_autopilot_goal_completion(self):
        adapter = MinecraftAdapter(mode="simulated")
        sim = adapter.sim

        # Place 4 oak logs in a row
        for i in range(1, 5):
            sim.set_block(i, 64, 0, "oak_log")

        autopilot = SpinalCordAutopilot(adapter=adapter)

        # Autonomous mining motor routine (20Hz System 1)
        def mine_corridor(adap: MinecraftAdapter, params: dict):
            target = params["target_block"]
            needed = params["needed_count"]
            cur_count = adap.sim.inventory.get(target, 0)
            if cur_count >= needed:
                return {"stop": True, "goal_achieved": True, "message": f"Mined {cur_count} {target}"}

            # Find next block in front
            for x in range(1, 10):
                b = adap.sim.get_block(x, 64, 0)
                if b.name == target:
                    res = adap.execute_action("dig", {"x": x, "y": 64, "z": 0})
                    return {"stop": False, "harvested": res.get("harvested", False)}

            return {"stop": True, "precondition_failed": True, "message": "No more target blocks in path"}

        report = autopilot.execute_skill_routine(
            intent="Mine 3 oak logs",
            skill_fn=mine_corridor,
            skill_params={"target_block": "oak_log", "needed_count": 3},
            max_ticks=20
        )

        self.assertEqual(report.status, AutopilotStatus.GOAL_COMPLETED)
        self.assertEqual(report.inventory_delta.get("oak_log"), 3)
        self.assertGreater(report.actions_executed, 0)

    def test_spinal_reflex_threat_interrupt(self):
        adapter = MinecraftAdapter(mode="simulated")
        transducer = StreamingVideoTransducer()
        transducer.register_roi("health_bar", (0, 0, 100, 30))

        autopilot = SpinalCordAutopilot(adapter=adapter, transducer=transducer)

        # Pre-seed sensory event: simulated sudden health drop / damage transient
        fake_threat = SensoryEvent(
            event_type="TRANSIENT_SPIKE",
            channel="health_bar",
            timestamp_ms=100.0,
            frame_index=15,
            magnitude=25.0,
            confidence=0.95,
            metadata={"z_score": 5.4}
        )
        transducer.event_queue.put_nowait(fake_threat)

        def dummy_motor_routine(adap, params):
            return {"stop": False}

        report = autopilot.execute_skill_routine(
            intent="Explore mine corridor",
            skill_fn=dummy_motor_routine,
            skill_params={},
            max_ticks=10,
            stop_on_threat=True
        )

        self.assertEqual(report.status, AutopilotStatus.THREAT_INTERRUPT)
        self.assertIn("Spinal reflex", report.explanation)
        self.assertIsNotNone(report.interrupt_event)
        # Verify emergency retreat action took place in the environment
        self.assertEqual(adapter.sim.player_pos[0], -3.0)

    def test_executive_cortex_intent_dispatch_and_evaporation(self):
        cortex = ExecutiveCortex()
        sim = cortex.adapter.sim

        for i in range(1, 4):
            sim.set_block(i, 64, 0, "oak_log")

        def autonomous_gather(adap, params):
            count = adap.sim.inventory.get("oak_log", 0)
            if count >= params["count"]:
                return {"stop": True, "goal_achieved": True}
            for x in range(1, 5):
                if adap.sim.get_block(x, 64, 0).name == "oak_log":
                    adap.execute_action("dig", {"x": x, "y": 64, "z": 0})
                    return {"stop": False}
            return {"stop": True, "precondition_failed": True}

        # Dispatch intent with expected prediction
        report = cortex.dispatch_intent(
            intent="Gather 2 oak logs",
            skill_fn=autonomous_gather,
            skill_params={"count": 2},
            expected_inventory_delta={"oak_log": 2}
        )

        self.assertEqual(report.status, AutopilotStatus.GOAL_COMPLETED)
        self.assertEqual(report.inventory_delta.get("oak_log"), 2)

        # Verify Working Memory Evaporation occurred
        stats = cortex.working_memory.stats()
        self.assertGreater(stats["evaporated_tokens_saved"], 0)
        messages = cortex.working_memory.get_messages_for_llm()
        self.assertIn("[Evaporated Routine]", messages[-1]["content"])

        # Verify EvidenceLedger recorded the verified procedural skill
        self.assertEqual(len(cortex.evidence_ledger.atoms), 1)
        self.assertIn("Gather 2 oak logs", cortex.evidence_ledger.atoms[0].claim)


if __name__ == "__main__":
    unittest.main()
