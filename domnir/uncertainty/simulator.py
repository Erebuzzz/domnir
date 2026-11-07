"""Physics simulation wrapper and sensitivity analyzer under plant uncertainty."""

from __future__ import annotations

import collections
import os
from pathlib import Path
from typing import Any, Callable, Sequence
import mujoco
import numpy as np

from domnir.contracts.stl import SafetyContract, STLMonitor, STLRobustnessResult
from domnir.spec import GeneratedController
from .models import (
    ParameterizedSuite,
    PlantUncertaintyConfig,
    SensitivityMetric,
    UncertaintyReport,
)


def resolve_model_path(model_path: Path | str | None = None) -> Path:
    """Resolve the Crazyflie 2 MuJoCo model XML file location."""
    if model_path is not None:
        p = Path(model_path)
        if p.is_file():
            return p
    env_path = os.environ.get("DOMNIR_SPIKE_MODEL")
    if env_path and Path(env_path).is_file():
        return Path(env_path)
    candidates = [
        Path.cwd() / ".cache" / "mujoco_menagerie" / "bitcraze_crazyflie_2" / "cf2.xml",
        Path(__file__).resolve().parents[2] / ".cache" / "mujoco_menagerie" / "bitcraze_crazyflie_2" / "cf2.xml",
        Path(__file__).resolve().parents[1] / ".cache" / "mujoco_menagerie" / "bitcraze_crazyflie_2" / "cf2.xml",
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    return candidates[0]


def normalize_action_vector(action: Any, action_dim: int = 4) -> np.ndarray:
    """Normalize raw controller actions (list, tuple, numpy array, or dict) to numpy vector."""
    if isinstance(action, dict):
        thrust = float(action.get("thrust", 0.0))
        mx = float(action.get("moment_x", 0.0))
        my = float(action.get("moment_y", 0.0))
        mz = float(action.get("moment_z", 0.0))
        return np.array([thrust, mx, my, mz], dtype=np.float64)
    if isinstance(action, (list, tuple, np.ndarray)):
        arr = np.array(action, dtype=np.float64)
        if len(arr) < action_dim:
            padded = np.zeros(action_dim, dtype=np.float64)
            padded[: len(arr)] = arr
            return padded
        return arr[:action_dim].astype(np.float64)
    return np.zeros(action_dim, dtype=np.float64)


class ActuatorDelayQueue:
    """FIFO queue to model discrete actuator communication and hardware latency."""

    def __init__(
        self,
        delay_steps: int = 0,
        default_action: Sequence[float] | np.ndarray | None = None,
        action_dim: int = 4,
    ) -> None:
        self.delay_steps = max(0, int(delay_steps))
        self.action_dim = action_dim
        if default_action is not None:
            self._default = np.array(default_action, dtype=np.float64)
        else:
            self._default = np.zeros(self.action_dim, dtype=np.float64)
        self._queue: collections.deque[np.ndarray] = collections.deque()
        self.reset()

    def reset(self) -> None:
        self._queue.clear()
        for _ in range(self.delay_steps):
            self._queue.append(self._default.copy())

    def push_and_pop(self, action: Sequence[float] | np.ndarray) -> np.ndarray:
        act = np.array(action, dtype=np.float64)
        if self.delay_steps == 0:
            return act
        self._queue.append(act)
        return self._queue.popleft()

    def __len__(self) -> int:
        return len(self._queue)


class UncertaintySimulationWrapper:
    """Simulation wrapper applying physical plant uncertainty and observation noise."""

    def __init__(
        self,
        model: mujoco.MjModel | Path | str | None = None,
        config: PlantUncertaintyConfig | None = None,
    ) -> None:
        self.config = config or PlantUncertaintyConfig()
        self.rng = np.random.default_rng(self.config.seed)

        self.model: mujoco.MjModel | None = None
        self.data: mujoco.MjData | None = None
        self.body_id: int = -1
        self.original_mass: float | None = None
        self.original_inertia: np.ndarray | None = None

        if model is not None or resolve_model_path().is_file():
            resolved = resolve_model_path(model if isinstance(model, (Path, str)) else None)
            if isinstance(model, mujoco.MjModel):
                self.model = model
            elif resolved.is_file():
                self.model = mujoco.MjModel.from_xml_path(str(resolved))

            if self.model is not None:
                self._apply_plant_modifications()
                self.data = mujoco.MjData(self.model)

        action_dim = self.model.nu if self.model is not None else 4
        self.delay_queue = ActuatorDelayQueue(
            delay_steps=self.config.actuator_delay_steps,
            action_dim=action_dim,
        )

    def _apply_plant_modifications(self) -> None:
        if self.model is None:
            return
        self.body_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, "cf2")
        if self.body_id >= 0:
            self.original_mass = float(self.model.body_mass[self.body_id])
            self.original_inertia = np.array(self.model.body_inertia[self.body_id], dtype=np.float64)
            if self.config.mass_scale != 1.0:
                self.model.body_mass[self.body_id] = self.original_mass * self.config.mass_scale
                self.model.body_inertia[self.body_id] = self.original_inertia * self.config.mass_scale

        if self.config.drag_scale != 1.0:
            self.model.opt.density = float(self.model.opt.density) * self.config.drag_scale
            self.model.opt.viscosity = float(self.model.opt.viscosity) * self.config.drag_scale

    def perturb_observation(self, observation: dict[str, Any]) -> dict[str, Any]:
        """Inject zero-mean Gaussian noise into state observations using deterministic seed."""
        perturbed = dict(observation)
        if self.config.position_noise_std_m > 0.0 and "position_m" in observation:
            pos = np.array(observation["position_m"], dtype=np.float64)
            noise = self.rng.normal(0.0, self.config.position_noise_std_m, size=pos.shape)
            perturbed["position_m"] = (pos + noise).tolist()

        if self.config.velocity_noise_std_mps > 0.0 and "velocity_mps" in observation:
            vel = np.array(observation["velocity_mps"], dtype=np.float64)
            noise = self.rng.normal(0.0, self.config.velocity_noise_std_mps, size=vel.shape)
            perturbed["velocity_mps"] = (vel + noise).tolist()

        return perturbed

    def process_action(self, action: Any) -> np.ndarray:
        """Buffer action in FIFO latency queue, scale by thrust factor, and clip to limits."""
        dim = self.model.nu if self.model is not None else 4
        act_vec = normalize_action_vector(action, dim)
        delayed = self.delay_queue.push_and_pop(act_vec)
        scaled = np.array(delayed, dtype=np.float64) * self.config.thrust_scale
        if self.model is not None and hasattr(self.model, "actuator_ctrlrange"):
            ctrl_min = self.model.actuator_ctrlrange[:, 0]
            ctrl_max = self.model.actuator_ctrlrange[:, 1]
            scaled = np.clip(scaled, ctrl_min, ctrl_max)
        return scaled

    def run_simulation(
        self,
        controller: Any,
        scenario: Any = None,
        contract: SafetyContract | None = None,
        *,
        initial_altitude_m: float | None = None,
        disturbance_force_z: float | None = None,
        steps: int | None = None,
        trial_id: str = "uncertainty_trial",
    ) -> list[dict[str, Any]]:
        """Run full closed-loop simulation with uncertainty modifications and record trajectory."""
        if self.model is None:
            raise RuntimeError("MuJoCo model is not loaded. Cannot run simulation.")

        c = contract or SafetyContract()

        if initial_altitude_m is not None:
            init_z = float(initial_altitude_m)
        elif scenario is not None and hasattr(scenario, "initial_altitude_m"):
            init_z = float(scenario.initial_altitude_m)
        else:
            init_z = float(c.target_altitude_m)

        if disturbance_force_z is not None:
            dist_f = float(disturbance_force_z)
        elif scenario is not None and hasattr(scenario, "disturbance_force_z"):
            dist_f = float(scenario.disturbance_force_z)
        else:
            dist_f = 0.0

        pulse_start = float(getattr(scenario, "pulse_start_s", 0.0)) if scenario else 0.0
        pulse_dur = float(getattr(scenario, "pulse_duration_s", 0.0)) if scenario else 0.0

        num_steps = steps if steps is not None else c.physics_steps
        if num_steps <= 0:
            num_steps = 200

        if hasattr(controller, "observe") and callable(controller.observe):
            observe_fn = controller.observe
        elif callable(controller):
            observe_fn = controller
        elif isinstance(controller, (GeneratedController, str)):
            source_code = controller.source_code if isinstance(controller, GeneratedController) else controller
            from domnir.evaluator import get_builtin_controller_fn
            builtin_fn = get_builtin_controller_fn(source_code)
            if builtin_fn is not None:
                observe_fn = builtin_fn
            else:
                from domnir.evaluator import SafeControllerEvaluator, is_microvm_available
                if not SafeControllerEvaluator.is_execution_available():
                    raise RuntimeError(
                        "BLOCKED: ISOLATION_UNAVAILABLE: MicroVM hardware acceleration (/dev/kvm) is required to execute untrusted controller code."
                    )
                from domnir.api.jobs import _MicroVMGuestStream, _IsolatedSubprocessGuestStream
                from domnir.sandbox import SandboxLease
                import shutil
                import json
                if is_microvm_available():
                    msb_path = Path(os.environ.get("DOMNIR_MSB") or shutil.which("msb"))
                    lease = SandboxLease(msb_path, duration_seconds=60)
                    lease.__enter__()
                    lease.install_controller(source_code.encode("utf-8"))
                    stream = _MicroVMGuestStream(lease)
                else:
                    stream = _IsolatedSubprocessGuestStream(source_code)

                def sandboxed_observe(obs: dict[str, Any]) -> Any:
                    resp_str = stream.exchange(obs)
                    return json.loads(resp_str)

                observe_fn = sandboxed_observe
        else:
            raise ValueError(f"Controller must be callable or define an observe method, got {type(controller)}")

        self.data = mujoco.MjData(self.model)
        self.data.qpos[2] = init_z
        mujoco.mj_forward(self.model, self.data)

        self.rng = np.random.default_rng(self.config.seed)
        self.delay_queue.reset()

        trajectory: list[dict[str, Any]] = []
        dt = float(self.model.opt.timestep)

        for step_idx in range(num_steps):
            sim_time = float(self.data.time)
            record = {
                "step_index": step_idx,
                "sim_time_s": sim_time,
                "position_m": self.data.qpos[:3].tolist(),
                "velocity_mps": self.data.qvel[:3].tolist(),
                "orientation_quat_wxyz": self.data.qpos[3:7].tolist(),
                "body_angular_velocity_rps": self.data.qvel[3:6].tolist(),
            }
            trajectory.append(record)

            clean_obs = {
                "schema_version": "1.0",
                "trial_id": trial_id,
                "step_index": step_idx,
                "sim_time_s": sim_time,
                "dt_s": dt,
                "position_m": self.data.qpos[:3].tolist(),
                "velocity_mps": self.data.qvel[:3].tolist(),
                "orientation_quat_wxyz": self.data.qpos[3:7].tolist(),
                "body_angular_velocity_rps": self.data.qvel[3:6].tolist(),
                "target_position_m": [0.0, 0.0, c.target_altitude_m],
                "target_altitude_m": c.target_altitude_m,
            }

            noisy_obs = self.perturb_observation(clean_obs)
            raw_action = observe_fn(noisy_obs)
            effective_action = self.process_action(raw_action)

            self.data.ctrl[:] = effective_action

            if self.body_id >= 0:
                if scenario is not None:
                    from domnir.scenario import calculate_applied_disturbance
                    f_applied = calculate_applied_disturbance(scenario, sim_time)
                else:
                    f_applied = dist_f
                self.data.xfrc_applied[self.body_id, 2] = f_applied

            mujoco.mj_step(self.model, self.data)

        final_record = {
            "step_index": num_steps,
            "sim_time_s": float(self.data.time),
            "position_m": self.data.qpos[:3].tolist(),
            "velocity_mps": self.data.qvel[:3].tolist(),
            "orientation_quat_wxyz": self.data.qpos[3:7].tolist(),
            "body_angular_velocity_rps": self.data.qvel[3:6].tolist(),
        }
        trajectory.append(final_record)
        return trajectory

    def evaluate_controller(
        self,
        controller: Any,
        scenario: Any = None,
        contract: SafetyContract | None = None,
        **kwargs: Any,
    ) -> STLRobustnessResult:
        """Execute simulation and return quantitative STL robustness result."""
        c = contract or SafetyContract()
        traj = self.run_simulation(controller, scenario=scenario, contract=c, **kwargs)
        return STLMonitor.evaluate_trajectory(c, traj)


class SensitivityAnalyzer:
    """Evaluates controller robustness across parameterized plant variants to quantify uncertainty."""

    def __init__(
        self,
        contract: SafetyContract | None = None,
        model_path: Path | str | None = None,
        suite: dict[str, PlantUncertaintyConfig] | None = None,
        evaluator: Callable[..., STLRobustnessResult] | None = None,
    ) -> None:
        self.contract = contract or SafetyContract()
        self.model_path = resolve_model_path(model_path) if (model_path or resolve_model_path().is_file()) else None
        self.suite = suite or ParameterizedSuite.get_suite()
        self.evaluator = evaluator

    def _evaluate_variant(
        self,
        controller: Any,
        config: PlantUncertaintyConfig,
        contract: SafetyContract,
        scenario: Any,
    ) -> STLRobustnessResult:
        if self.evaluator is not None:
            try:
                return self.evaluator(controller, config, contract, scenario)
            except TypeError:
                return self.evaluator(controller, config)

        wrapper = UncertaintySimulationWrapper(model=self.model_path, config=config)
        return wrapper.evaluate_controller(controller, scenario=scenario, contract=contract)

    def analyze(
        self,
        controller: Any,
        scenario: Any = None,
        contract: SafetyContract | None = None,
    ) -> UncertaintyReport:
        """Run controller across the ParameterizedSuite and compute sensitivity metrics."""
        active_contract = contract or self.contract

        nominal_config = self.suite.get("nominal", ParameterizedSuite.nominal())
        nominal_result = self._evaluate_variant(controller, nominal_config, active_contract, scenario)
        nominal_rho = float(nominal_result.min_robustness)

        variant_robustness: dict[str, float] = {}
        variant_results: dict[str, STLRobustnessResult] = {}
        sensitivities: list[SensitivityMetric] = []

        for variant_name, config in self.suite.items():
            if variant_name == "nominal":
                res = nominal_result
            else:
                res = self._evaluate_variant(controller, config, active_contract, scenario)

            rho = float(res.min_robustness)
            variant_robustness[variant_name] = rho
            variant_results[variant_name] = res

            if variant_name != "nominal":
                sens_coeff = abs(nominal_rho - rho)
                metric = SensitivityMetric(
                    parameter_name=variant_name,
                    nominal_robustness=round(nominal_rho, 6),
                    perturbed_robustness=round(rho, 6),
                    sensitivity_coefficient=round(sens_coeff, 6),
                    causes_violation=rho < 0.0,
                )
                sensitivities.append(metric)

        sensitivities.sort(key=lambda m: m.sensitivity_coefficient, reverse=True)

        total_variants = len(variant_robustness)
        passing = sum(1 for rho in variant_robustness.values() if rho >= 0.0)
        failing = sum(1 for rho in variant_robustness.values() if rho < 0.0)
        min_rho = min(variant_robustness.values()) if variant_robustness else 0.0
        worst_variant = min(variant_robustness.items(), key=lambda item: item[1])[0] if variant_robustness else "none"
        most_sensitive = sensitivities[0].parameter_name if sensitivities else "none"

        sens_coeff_str = f"{sensitivities[0].sensitivity_coefficient:.4f}" if sensitivities else "0.0000"
        summary = (
            f"Evaluated {total_variants} plant uncertainty variants: "
            f"{passing} passing, {failing} failing. "
            f"Minimum robustness across suite is {min_rho:+.4f} (worst variant: '{worst_variant}'). "
            f"Dominant failure risk parameter: '{most_sensitive}' "
            f"(sensitivity coefficient: {sens_coeff_str})."
        )

        return UncertaintyReport(
            total_variants_evaluated=total_variants,
            variants_passing=passing,
            variants_failing=failing,
            min_robustness_across_variants=round(min_rho, 6),
            worst_variant_name=worst_variant,
            most_sensitive_parameter=most_sensitive,
            parameter_sensitivities=sensitivities,
            summary=summary,
            variant_robustness=variant_robustness,
        )
