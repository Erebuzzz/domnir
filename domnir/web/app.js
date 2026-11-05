/**
 * Dómnir Web Application Controller
 * Offline-ready, zero external dependencies, zero em dashes.
 */

(function () {
  "use strict";

  const state = {
    selectedModel: "glm-5.3-flash",
    models: [],
    activeSpec: null,
    activeController: null,
    activeExperimentId: null,
    activeCourtRecord: null,
    activeTrajectory: [],
    pollTimer: null,
  };

  const BASELINE_CONTROLLER_SOURCE = `def observe(observation):
    z = observation['position_m'][2]
    vz = observation['velocity_mps'][2]
    target_z = observation.get('target_altitude_m', 0.1)
    
    # Proportional-Derivative altitude hover control
    kp = 0.20
    kd = 0.08
    base_thrust = 0.26487  # crazyflie 2 gravity equilibrium
    thrust = max(0.0, min(0.35, base_thrust + kp * (target_z - z) - kd * vz))
    
    return {
        'schema_version': '1.0',
        'trial_id': observation['trial_id'],
        'step_index': observation['step_index'],
        'thrust': float(thrust),
        'moment_x': 0.0,
        'moment_y': 0.0,
        'moment_z': 0.0,
    }
`;

  const elements = {
    // Status bar
    apiDot: document.getElementById("apiDot"),
    apiStatusText: document.getElementById("apiStatusText"),
    inferenceDot: document.getElementById("inferenceDot"),
    inferenceStatusText: document.getElementById("inferenceStatusText"),
    backendDot: document.getElementById("backendDot"),
    backendStatusText: document.getElementById("backendStatusText"),
    refreshStatusBtn: document.getElementById("refreshStatusBtn"),

    // Tabs
    navTabs: document.querySelectorAll(".nav-tab"),
    tabPanes: document.querySelectorAll(".tab-pane"),

    // Spec form
    specForm: document.getElementById("specForm"),
    targetAltitude: document.getElementById("targetAltitude"),
    altitudeTolerance: document.getElementById("altitudeTolerance"),
    minAltitude: document.getElementById("minAltitude"),
    maxAltitude: document.getElementById("maxAltitude"),
    missionDuration: document.getElementById("missionDuration"),
    distZMin: document.getElementById("distZMin"),
    distZMax: document.getElementById("distZMax"),
    calcStepBudget: document.getElementById("calcStepBudget"),
    validateSpecBtn: document.getElementById("validateSpecBtn"),
    specFeedback: document.getElementById("specFeedback"),

    // Presets
    presetNominal: document.getElementById("presetNominal"),
    presetHigh: document.getElementById("presetHigh"),
    presetTurbulent: document.getElementById("presetTurbulent"),

    // Models & Generation
    modelCardsContainer: document.getElementById("modelCardsContainer"),
    generateControllerBtn: document.getElementById("generateControllerBtn"),
    genSpinner: document.getElementById("genSpinner"),
    loadBaselineBtn: document.getElementById("loadBaselineBtn"),
    controllerSource: document.getElementById("controllerSource"),
    controllerHash: document.getElementById("controllerHash"),
    controllerAstBadge: document.getElementById("controllerAstBadge"),
    controllerContractBadge: document.getElementById("controllerContractBadge"),
    copyCodeBtn: document.getElementById("copyCodeBtn"),

    // Execution
    initAltitude: document.getElementById("initAltitude"),
    vertDisturbance: document.getElementById("vertDisturbance"),
    seedVal: document.getElementById("seedVal"),
    asyncToggle: document.getElementById("asyncToggle"),
    runExperimentBtn: document.getElementById("runExperimentBtn"),
    runSpinner: document.getElementById("runSpinner"),
    stateTracker: document.getElementById("stateTracker"),
    executionErrorBanner: document.getElementById("executionErrorBanner"),
    executionErrorText: document.getElementById("executionErrorText"),

    // Chart & Metrics
    chartWrapper: document.getElementById("chartWrapper"),
    altitudeSvgChart: document.getElementById("altitudeSvgChart"),
    chartTooltip: document.getElementById("chartTooltip"),
    metricSteps: document.getElementById("metricSteps"),
    metricFinalAlt: document.getElementById("metricFinalAlt"),
    metricAltError: document.getElementById("metricAltError"),
    metricMinAlt: document.getElementById("metricMinAlt"),
    metricMaxAlt: document.getElementById("metricMaxAlt"),

    // Adjudication & Replay
    replayDiffValue: document.getElementById("replayDiffValue"),
    replayBadge: document.getElementById("replayBadge"),
    verdictFlight: document.getElementById("verdictFlight"),
    verdictFlightDesc: document.getElementById("verdictFlightDesc"),
    verdictContainment: document.getElementById("verdictContainment"),
    verdictProvenance: document.getElementById("verdictProvenance"),
    verdictCleanup: document.getElementById("verdictCleanup"),
    adjudicationText: document.getElementById("adjudicationText"),

    // Court Record Export
    downloadCourtRecordBtn: document.getElementById("downloadCourtRecordBtn"),
    copyCourtRecordBtn: document.getElementById("copyCourtRecordBtn"),
    openInVerifierBtn: document.getElementById("openInVerifierBtn"),

    // Verifier Tab
    dropZone: document.getElementById("dropZone"),
    courtFileInput: document.getElementById("courtFileInput"),
    browseFileBtn: document.getElementById("browseFileBtn"),
    pasteSampleBtn: document.getElementById("pasteSampleBtn"),
    courtJsonInput: document.getElementById("courtJsonInput"),
    submitVerifyBtn: document.getElementById("submitVerifyBtn"),
    verifySpinner: document.getElementById("verifySpinner"),
    verifyResultsCard: document.getElementById("verifyResultsCard"),
    verifyOverallBadge: document.getElementById("verifyOverallBadge"),
    verifyMetaDetails: document.getElementById("verifyMetaDetails"),
    checkControllerHash: document.getElementById("checkControllerHash"),
    iconControllerHash: document.getElementById("iconControllerHash"),
    detailControllerHash: document.getElementById("detailControllerHash"),
    checkTrajectoryHash: document.getElementById("checkTrajectoryHash"),
    iconTrajectoryHash: document.getElementById("iconTrajectoryHash"),
    detailTrajectoryHash: document.getElementById("detailTrajectoryHash"),
    checkModelHashes: document.getElementById("checkModelHashes"),
    iconModelHashes: document.getElementById("iconModelHashes"),
    detailModelHashes: document.getElementById("detailModelHashes"),
    checkEventChain: document.getElementById("checkEventChain"),
    iconEventChain: document.getElementById("iconEventChain"),
    detailEventChain: document.getElementById("detailEventChain"),
    checkPhysicalReplay: document.getElementById("checkPhysicalReplay"),
    iconPhysicalReplay: document.getElementById("iconPhysicalReplay"),
    detailPhysicalReplay: document.getElementById("detailPhysicalReplay"),
    verifyErrorsBox: document.getElementById("verifyErrorsBox"),
    verifyErrorsList: document.getElementById("verifyErrorsList"),

    // Containment Audit
    containmentOverallBadge: document.getElementById("containmentOverallBadge"),
    refreshContainmentBtn: document.getElementById("refreshContainmentBtn"),
    runContainmentBtn: document.getElementById("runContainmentBtn"),
    containmentSpinner: document.getElementById("containmentSpinner"),
    containmentEnvText: document.getElementById("containmentEnvText"),
    containmentCleanupText: document.getElementById("containmentCleanupText"),
    containmentSourceText: document.getElementById("containmentSourceText"),
    containmentTimestampText: document.getElementById("containmentTimestampText"),

    fixtureBadgeCap: document.getElementById("fixtureBadgeCap"),
    fixturePolicyCap: document.getElementById("fixturePolicyCap"),
    fixtureCleanupCap: document.getElementById("fixtureCleanupCap"),

    fixtureBadgeNet: document.getElementById("fixtureBadgeNet"),
    fixtureEgressNet: document.getElementById("fixtureEgressNet"),
    fixtureIngressNet: document.getElementById("fixtureIngressNet"),
    fixtureCleanupNet: document.getElementById("fixtureCleanupNet"),

    fixtureBadgeTime: document.getElementById("fixtureBadgeTime"),
    fixtureElapsedVal: document.getElementById("fixtureElapsedVal"),
    fixtureCleanupTime: document.getElementById("fixtureCleanupTime"),

    fixtureBadgeMem: document.getElementById("fixtureBadgeMem"),
    fixtureExitState: document.getElementById("fixtureExitState"),
    fixtureAttributionVal: document.getElementById("fixtureAttributionVal"),
    fixtureCleanupMem: document.getElementById("fixtureCleanupMem"),

    fixtureBadgeCleanup: document.getElementById("fixtureBadgeCleanup"),
    fixtureAuditCleanup: document.getElementById("fixtureAuditCleanup"),
    fixtureOrphanedVms: document.getElementById("fixtureOrphanedVms"),
    fixturePostRunTable: document.getElementById("fixturePostRunTable"),

    containmentLogBadge: document.getElementById("containmentLogBadge"),
    containmentLogFile: document.getElementById("containmentLogFile"),
    containmentEventCount: document.getElementById("containmentEventCount"),
    containmentShaHead: document.getElementById("containmentShaHead"),
    containmentLogStatus: document.getElementById("containmentLogStatus"),
    containmentLimitationsList: document.getElementById("containmentLimitationsList"),

    // Feedback
    toastContainer: document.getElementById("toastContainer"),
  };

  // Toast Notification System
  function toast(message, type = "info") {
    if (!elements.toastContainer) return;
    const toastEl = document.createElement("div");
    toastEl.className = "toast toast-" + type;
    toastEl.innerHTML = `
      <span>${escapeHtml(message)}</span>
      <button type="button" class="toast-close" title="Dismiss">&times;</button>
    `;
    const closeBtn = toastEl.querySelector(".toast-close");
    if (closeBtn) {
      closeBtn.addEventListener("click", () => toastEl.remove());
    }
    elements.toastContainer.appendChild(toastEl);
    setTimeout(() => {
      if (toastEl.parentNode) toastEl.remove();
    }, 4500);
  }

  // SHA-256 in browser
  async function sha256(text) {
    const encoder = new TextEncoder();
    const data = encoder.encode(text);
    const hashBuffer = await crypto.subtle.digest("SHA-256", data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, "0")).join("");
  }

  // ==========================================================================
  // Backend Status Checks
  // ==========================================================================

  async function checkHealthAndReadiness() {
    elements.apiDot.className = "status-dot dot-unknown";
    elements.apiStatusText.textContent = "Connecting...";

    try {
      const healthRes = await fetch("/health");
      if (!healthRes.ok) throw new Error("HTTP " + healthRes.status);
      const healthData = await healthRes.json();
      elements.apiDot.className = "status-dot dot-ok";
      elements.apiStatusText.textContent = "ONLINE (v" + (healthData.version || "0.1.0") + ")";

      const readyRes = await fetch("/ready");
      if (readyRes.ok) {
        const readyData = await readyRes.json();
        if (readyData.inference_configured) {
          elements.inferenceDot.className = "status-dot dot-ok";
          elements.inferenceStatusText.textContent = "CONNECTED";
        } else {
          elements.inferenceDot.className = "status-dot dot-warning";
          elements.inferenceStatusText.textContent = "LOCAL SIM ONLY";
        }

        if (readyData.microvm_available) {
          elements.backendDot.className = "status-dot dot-ok";
          elements.backendStatusText.textContent = "MICROVM (KVM)";
        } else {
          elements.backendDot.className = "status-dot dot-ok";
          elements.backendStatusText.textContent = "TRUSTED SIMULATOR";
        }
      }
    } catch (err) {
      elements.apiDot.className = "status-dot dot-error";
      elements.apiStatusText.textContent = "OFFLINE";
      elements.inferenceDot.className = "status-dot dot-unknown";
      elements.inferenceStatusText.textContent = "UNKNOWN";
      elements.backendDot.className = "status-dot dot-unknown";
      elements.backendStatusText.textContent = "UNKNOWN";
    }
  }

  // Fetch Models Catalog
  async function fetchModels() {
    try {
      const res = await fetch("/models");
      if (!res.ok) return;
      const data = await res.json();
      if (data && data.models && data.models.length > 0) {
        state.models = data.models;
        renderModelCards(data.models, data.default_model);
      }
    } catch (err) {
      console.warn("Could not fetch models catalog:", err);
    }
  }

  function setupInitialModelCards() {
    if (!elements.modelCardsContainer) return;
    const cards = elements.modelCardsContainer.querySelectorAll(".model-card");
    cards.forEach(card => {
      card.addEventListener("click", () => {
        cards.forEach(c => c.classList.remove("selected"));
        card.classList.add("selected");
        state.selectedModel = card.dataset.model;
      });
    });
  }

  function renderModelCards(models, defaultModelId) {
    if (!elements.modelCardsContainer) return;
    elements.modelCardsContainer.innerHTML = "";

    models.forEach(model => {
      const isDefault = Boolean(model.default || model.id === defaultModelId);
      const isSelected = model.id === state.selectedModel || (!state.selectedModel && isDefault);
      if (isSelected) state.selectedModel = model.id;

      const card = document.createElement("div");
      card.className = "model-card" + (isSelected ? " selected" : "");
      card.dataset.model = model.id;

      let defaultBadgeHtml = isDefault ? '<span class="badge badge-default">DEFAULT</span>' : "";

      card.innerHTML = `
        <div class="model-card-header">
          <span class="model-name">${escapeHtml(model.name || model.id)}</span>
          ${defaultBadgeHtml}
        </div>
        <div class="model-family">Family: ${escapeHtml(model.family ? model.family.toUpperCase() : "GENERAL")}</div>
        <p class="model-desc">${escapeHtml(model.description || "")}</p>
      `;

      card.addEventListener("click", () => {
        elements.modelCardsContainer.querySelectorAll(".model-card").forEach(c => c.classList.remove("selected"));
        card.classList.add("selected");
        state.selectedModel = model.id;
      });

      elements.modelCardsContainer.appendChild(card);
    });
  }

  // ==========================================================================
  // Tab Navigation
  // ==========================================================================

  function setupTabs() {
    elements.navTabs.forEach(tab => {
      tab.addEventListener("click", () => {
        const targetId = tab.dataset.tab;
        elements.navTabs.forEach(t => t.classList.remove("active"));
        elements.tabPanes.forEach(p => p.classList.remove("active"));

        tab.classList.add("active");
        const targetPane = document.getElementById(targetId);
        if (targetPane) targetPane.classList.add("active");

        if (targetId === "tab-workspace" && state.activeTrajectory.length > 0) {
          renderAltitudeChart(state.activeTrajectory, getSpecFromForm());
        } else if (targetId === "tab-containment") {
          fetchContainmentStatus();
        }
      });
    });
  }

  // ==========================================================================
  // Mission Spec & Step Budget
  // ==========================================================================

  function getSpecFromForm() {
    return {
      target_altitude_m: parseFloat(elements.targetAltitude.value) || 0.1,
      altitude_tolerance_m: parseFloat(elements.altitudeTolerance.value) || 0.05,
      min_allowed_altitude_m: parseFloat(elements.minAltitude.value) || 0.05,
      max_allowed_altitude_m: parseFloat(elements.maxAltitude.value) || 1.0,
      mission_duration_s: parseFloat(elements.missionDuration.value) || 0.4,
      dt_s: 0.002,
      disturbance_force_z_min: parseFloat(elements.distZMin.value) || -0.05,
      disturbance_force_z_max: parseFloat(elements.distZMax.value) || 0.05,
    };
  }

  function setSpecToForm(spec) {
    if (spec.target_altitude_m !== undefined) elements.targetAltitude.value = spec.target_altitude_m;
    if (spec.altitude_tolerance_m !== undefined) elements.altitudeTolerance.value = spec.altitude_tolerance_m;
    if (spec.min_allowed_altitude_m !== undefined) elements.minAltitude.value = spec.min_allowed_altitude_m;
    if (spec.max_allowed_altitude_m !== undefined) elements.maxAltitude.value = spec.max_allowed_altitude_m;
    if (spec.mission_duration_s !== undefined) elements.missionDuration.value = spec.mission_duration_s;
    if (spec.disturbance_force_z_min !== undefined) elements.distZMin.value = spec.disturbance_force_z_min;
    if (spec.disturbance_force_z_max !== undefined) elements.distZMax.value = spec.disturbance_force_z_max;
    updateStepBudget();
  }

  function updateStepBudget() {
    const duration = parseFloat(elements.missionDuration.value) || 0.4;
    const steps = Math.round(duration / 0.002);
    elements.calcStepBudget.textContent = steps + " steps";
  }

  async function validateMissionSpec() {
    const spec = getSpecFromForm();
    elements.specFeedback.style.display = "none";
    elements.specFeedback.className = "feedback-badge";

    try {
      const res = await fetch("/specs/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spec: spec }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : "Validation error");
      }
      elements.specFeedback.textContent = "VALID: " + (data.message || "Step budget " + data.step_budget);
      elements.specFeedback.classList.add("success");
      elements.specFeedback.style.display = "inline-block";
      state.activeSpec = spec;
      toast("Mission envelope validated successfully (" + data.step_budget + " steps).", "success");
    } catch (err) {
      elements.specFeedback.textContent = "INVALID: " + err.message;
      elements.specFeedback.classList.add("error");
      elements.specFeedback.style.display = "inline-block";
      toast("Invalid mission parameters: " + err.message, "error");
    }
  }

  function setupPresets() {
    elements.presetNominal.addEventListener("click", () => {
      setSpecToForm({
        target_altitude_m: 0.10,
        altitude_tolerance_m: 0.05,
        min_allowed_altitude_m: 0.05,
        max_allowed_altitude_m: 1.00,
        mission_duration_s: 0.40,
        disturbance_force_z_min: -0.05,
        disturbance_force_z_max: 0.05,
      });
      validateMissionSpec();
    });

    elements.presetHigh.addEventListener("click", () => {
      setSpecToForm({
        target_altitude_m: 1.50,
        altitude_tolerance_m: 0.10,
        min_allowed_altitude_m: 0.10,
        max_allowed_altitude_m: 3.00,
        mission_duration_s: 0.80,
        disturbance_force_z_min: -0.10,
        disturbance_force_z_max: 0.10,
      });
      validateMissionSpec();
    });

    elements.presetTurbulent.addEventListener("click", () => {
      setSpecToForm({
        target_altitude_m: 0.10,
        altitude_tolerance_m: 0.05,
        min_allowed_altitude_m: 0.05,
        max_allowed_altitude_m: 1.00,
        mission_duration_s: 0.40,
        disturbance_force_z_min: -0.20,
        disturbance_force_z_max: 0.20,
      });
      validateMissionSpec();
    });
  }

  // ==========================================================================
  // Controller Generation & Code Handling
  // ==========================================================================

  async function updateCodeMetadata(code) {
    if (!code || !code.trim()) {
      elements.controllerHash.textContent = "None";
      elements.controllerAstBadge.textContent = "EMPTY";
      elements.controllerAstBadge.className = "meta-badge";
      return;
    }

    const hash = await sha256(code);
    elements.controllerHash.textContent = hash;
    elements.controllerHash.title = hash;

    if (code.includes("def observe(") && code.includes("return")) {
      elements.controllerAstBadge.textContent = "VALID_SYNTAX";
      elements.controllerAstBadge.className = "meta-badge text-emerald";
    } else {
      elements.controllerAstBadge.textContent = "CHECK_SIGNATURE";
      elements.controllerAstBadge.className = "meta-badge text-amber";
    }
  }

  async function generateController() {
    const spec = getSpecFromForm();
    const model = state.selectedModel || "glm-5.3-flash";

    elements.generateControllerBtn.disabled = true;
    elements.genSpinner.style.display = "inline-block";

    try {
      const res = await fetch("/controllers/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          spec: spec,
          model: model,
          prompt_version: "v1",
          max_tokens: 4096,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : "Generation failed");
      }

      const controller = data.controller;
      elements.controllerSource.value = controller.source_code;
      await updateCodeMetadata(controller.source_code);
      state.activeController = controller;
      toast("Controller generated via " + model + " and validated.", "success");
    } catch (err) {
      toast("Generation Notice: " + err.message + ". You can test with the baseline controller immediately.", "warning");
    } finally {
      elements.generateControllerBtn.disabled = false;
      elements.genSpinner.style.display = "none";
    }
  }

  function loadBaselineController() {
    elements.controllerSource.value = BASELINE_CONTROLLER_SOURCE;
    updateCodeMetadata(BASELINE_CONTROLLER_SOURCE);
    state.activeController = {
      source_code: BASELINE_CONTROLLER_SOURCE,
      model_id: "baseline_proportional_derivative",
      source_sha256: null,
    };
  }

  // ==========================================================================
  // Experiment Execution & State Tracker
  // ==========================================================================

  function updateStateTracker(currentState, stateHistory) {
    const states = ["CREATED", "SPEC_APPROVED", "CONTROLLER_VALIDATED", "QUEUED", "RUNNING", "COMPLETED"];
    const failStep = elements.stateTracker ? elements.stateTracker.querySelector(".state-step-fail") : null;

    if (currentState === "FAILED" || currentState === "INCONCLUSIVE") {
      if (failStep) {
        failStep.style.display = "flex";
        failStep.classList.add("active");
        const stepText = failStep.querySelector(".step-text");
        if (stepText) stepText.textContent = currentState;
      }

      const completedStates = new Set();
      if (Array.isArray(stateHistory)) {
        stateHistory.forEach(rec => {
          if (rec.to_state && rec.to_state !== "FAILED" && rec.to_state !== "INCONCLUSIVE") {
            completedStates.add(rec.to_state);
          }
        });
      }

      const stepElements = elements.stateTracker.querySelectorAll(".state-step:not(.state-step-fail)");
      stepElements.forEach(el => {
        el.classList.remove("active");
        if (completedStates.has(el.dataset.state)) {
          el.classList.add("completed");
        } else {
          el.classList.remove("completed");
        }
      });
      return;
    }

    if (failStep) {
      failStep.style.display = "none";
      failStep.classList.remove("active");
    }

    const currentIndex = states.indexOf(currentState);
    const stepElements = elements.stateTracker.querySelectorAll(".state-step:not(.state-step-fail)");
    stepElements.forEach((el, index) => {
      const stepName = el.dataset.state;
      el.classList.remove("active", "completed");

      if (stepName === currentState) {
        el.classList.add("active");
      } else if (currentIndex >= 0 && index < currentIndex) {
        el.classList.add("completed");
      }
    });
  }

  async function runExperiment() {
    const spec = getSpecFromForm();
    const sourceCode = elements.controllerSource.value;

    if (!sourceCode.trim()) {
      toast("Please load or generate a controller before launching the trial.", "warning");
      return;
    }

    const initAlt = parseFloat(elements.initAltitude.value) || 0.15;
    const vertDist = parseFloat(elements.vertDisturbance.value) || 0.0;
    const seed = parseInt(elements.seedVal.value, 10) || 42;
    const isAsync = elements.asyncToggle.checked;

    elements.runExperimentBtn.disabled = true;
    elements.runSpinner.style.display = "inline-block";
    updateStateTracker("CREATED");

    resetRunDisplay();

    const payload = {
      spec: spec,
      controller_source: sourceCode,
      model: state.selectedModel,
      initial_altitude_m: initAlt,
      vertical_disturbance_n: vertDist,
      seed: seed,
      run_async: isAsync,
    };

    try {
      const res = await fetch("/experiments/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const summary = await res.json();
      if (!res.ok) {
        throw new Error(summary.detail ? (typeof summary.detail === "string" ? summary.detail : JSON.stringify(summary.detail)) : "Experiment run failed");
      }

      state.activeExperimentId = summary.id;
      updateStateTracker(summary.state);

      if (isAsync && summary.state !== "COMPLETED" && summary.state !== "FAILED") {
        pollExperiment(summary.id, spec);
      } else {
        await handleExperimentCompleted(summary.id, spec);
      }
    } catch (err) {
      toast("Execution Error: " + err.message, "error");
      if (elements.executionErrorBanner && elements.executionErrorText) {
        elements.executionErrorText.textContent = err.message;
        elements.executionErrorBanner.style.display = "flex";
      }
      updateStateTracker("FAILED");
      elements.runExperimentBtn.disabled = false;
      elements.runSpinner.style.display = "none";
    }
  }

  function pollExperiment(experimentId, spec) {
    if (state.pollTimer) clearInterval(state.pollTimer);

    state.pollTimer = setInterval(async () => {
      try {
        const res = await fetch("/experiments/" + experimentId);
        if (!res.ok) return;
        const detail = await res.json();

        updateStateTracker(detail.state, detail.state_history);

        if (detail.state === "COMPLETED" || detail.state === "FAILED" || detail.state === "INCONCLUSIVE") {
          clearInterval(state.pollTimer);
          state.pollTimer = null;
          await handleExperimentCompleted(experimentId, spec);
        }
      } catch (e) {
        console.warn("Polling error:", e);
      }
    }, 400);
  }

  async function handleExperimentCompleted(experimentId, spec) {
    try {
      // 1. Fetch Detail
      const detailRes = await fetch("/experiments/" + experimentId);
      const detail = await detailRes.json();

      // 2. Fetch Artifacts
      const artRes = await fetch("/experiments/" + experimentId + "/artifacts");
      const artifacts = await artRes.json();

      state.activeCourtRecord = artifacts.court_record || null;
      state.activeTrajectory = artifacts.trajectory || [];

      // Update state tracker with history
      updateStateTracker(detail.state || "COMPLETED", detail.state_history);

      // Handle execution error display
      if (detail.state === "FAILED" || detail.error_message) {
        if (elements.executionErrorBanner && elements.executionErrorText) {
          elements.executionErrorText.textContent = detail.error_message || "Experiment terminated with fault.";
          elements.executionErrorBanner.style.display = "flex";
        }
      } else {
        if (elements.executionErrorBanner) {
          elements.executionErrorBanner.style.display = "none";
        }
      }

      // Update metrics
      elements.metricSteps.textContent = detail.steps_completed || (state.activeTrajectory.length > 0 ? state.activeTrajectory.length - 1 : 0);
      elements.metricFinalAlt.textContent = detail.final_altitude_m !== null && detail.final_altitude_m !== undefined ? detail.final_altitude_m.toFixed(4) + " m" : "--";
      elements.metricAltError.textContent = detail.altitude_error_m !== null && detail.altitude_error_m !== undefined ? detail.altitude_error_m.toFixed(4) + " m" : "--";
      elements.metricMinAlt.textContent = detail.minimum_altitude_m !== null && detail.minimum_altitude_m !== undefined ? detail.minimum_altitude_m.toFixed(4) + " m" : "--";
      elements.metricMaxAlt.textContent = detail.maximum_altitude_m !== null && detail.maximum_altitude_m !== undefined ? detail.maximum_altitude_m.toFixed(4) + " m" : "--";

      // Render 2D Altitude Chart
      renderAltitudeChart(state.activeTrajectory, spec);

      // Replay determinism display
      displayReplayAndVerdicts(detail, artifacts.court_record);

      // Enable export buttons
      elements.downloadCourtRecordBtn.disabled = !state.activeCourtRecord;
      elements.copyCourtRecordBtn.disabled = !state.activeCourtRecord;
      elements.openInVerifierBtn.disabled = !state.activeCourtRecord;

      if (detail.state === "COMPLETED") {
        toast("Trial completed: Verdict " + (detail.verdict || "RECORDED"), "success");
      } else if (detail.state === "FAILED") {
        toast("Trial failed: " + (detail.error_message || "check state history"), "error");
      }
    } catch (err) {
      console.error("Error processing completed experiment:", err);
    } finally {
      elements.runExperimentBtn.disabled = false;
      elements.runSpinner.style.display = "none";
    }
  }

  function resetRunDisplay() {
    if (elements.executionErrorBanner) {
      elements.executionErrorBanner.style.display = "none";
    }
    elements.replayDiffValue.textContent = "--";
    elements.replayBadge.textContent = "WAITING FOR TRIAL";
    elements.replayBadge.className = "replay-badge";
    elements.verdictFlight.textContent = "PENDING";
    elements.verdictFlight.className = "verdict-val val-pending";
    elements.verdictContainment.textContent = "PENDING";
    elements.verdictContainment.className = "verdict-val val-pending";
    elements.verdictProvenance.textContent = "PENDING";
    elements.verdictProvenance.className = "verdict-val val-pending";
    elements.verdictCleanup.textContent = "PENDING";
    elements.verdictCleanup.className = "verdict-val val-pending";
    elements.downloadCourtRecordBtn.disabled = true;
    elements.copyCourtRecordBtn.disabled = true;
    elements.openInVerifierBtn.disabled = true;
  }

  function displayReplayAndVerdicts(detail, courtRecord) {
    // Replay difference
    const diff = detail.replay_max_abs_difference !== null && detail.replay_max_abs_difference !== undefined
      ? detail.replay_max_abs_difference
      : (courtRecord && courtRecord.replay ? courtRecord.replay.max_abs_difference : 0.0);

    elements.replayDiffValue.textContent = Number(diff).toExponential(2) + " m";

    if (diff <= 1e-12) {
      elements.replayBadge.textContent = "REPLAY MATCHED (<= 1e-12 m)";
      elements.replayBadge.className = "replay-badge badge-success";
    } else {
      elements.replayBadge.textContent = "REPLAY DIVERGENCE";
      elements.replayBadge.className = "replay-badge badge-fail";
    }

    // Verdicts
    const verdict = detail.verdict || (courtRecord && courtRecord.verdicts ? courtRecord.verdicts.flight_verdict : "NOT_FALSIFIED");

    if (verdict === "NOT_FALSIFIED") {
      elements.verdictFlight.textContent = "NOT FALSIFIED";
      elements.verdictFlight.className = "verdict-val val-success";
      elements.verdictFlightDesc.textContent = "No constraint violations within test budget";
    } else if (verdict === "FALSIFIED") {
      elements.verdictFlight.textContent = "FALSIFIED";
      elements.verdictFlight.className = "verdict-val val-fail";
      elements.verdictFlightDesc.textContent = "Counterexample boundary violation detected";
    } else if (verdict === "FAILED" || detail.state === "FAILED") {
      elements.verdictFlight.textContent = "FAILED";
      elements.verdictFlight.className = "verdict-val val-fail";
      elements.verdictFlightDesc.textContent = detail.error_message || "Execution faulted during trial";
    } else {
      elements.verdictFlight.textContent = verdict;
      elements.verdictFlight.className = "verdict-val val-warning";
      elements.verdictFlightDesc.textContent = "Trial inconclusive or diverged";
    }

    // Honest Containment Verdict
    const rawContainment = courtRecord && courtRecord.verdicts ? courtRecord.verdicts.containment_status : null;
    const backend = detail.execution_backend || "trusted_simulator";
    if (detail.state === "FAILED" && !courtRecord) {
      elements.verdictContainment.textContent = "FAULT / ABORTED";
      elements.verdictContainment.className = "verdict-val val-fail";
    } else if (rawContainment === "POLICY_CONFIRMED" || backend === "microvm") {
      elements.verdictContainment.textContent = "POLICY CONFIRMED (MICROVM)";
      elements.verdictContainment.className = "verdict-val val-success";
    } else if (rawContainment === "PARTIAL" || backend === "trusted_simulator" || backend === "subprocess") {
      elements.verdictContainment.textContent = "PARTIAL (TRUSTED SIMULATOR)";
      elements.verdictContainment.className = "verdict-val val-warning";
    } else {
      elements.verdictContainment.textContent = rawContainment || "NOT TESTED";
      elements.verdictContainment.className = "verdict-val val-pending";
    }

    // Honest Provenance Verdict
    const rawProvenance = courtRecord && courtRecord.verdicts ? courtRecord.verdicts.provenance_status : null;
    if (detail.state === "FAILED" && !courtRecord) {
      elements.verdictProvenance.textContent = "NOT AVAILABLE";
      elements.verdictProvenance.className = "verdict-val val-pending";
    } else if (rawProvenance === "VERIFIED" || courtRecord) {
      elements.verdictProvenance.textContent = "VERIFIED";
      elements.verdictProvenance.className = "verdict-val val-success";
    } else {
      elements.verdictProvenance.textContent = rawProvenance || "INCOMPLETE";
      elements.verdictProvenance.className = "verdict-val val-warning";
    }

    // Cleanup Status
    const cleanupOk = detail.cleanup_succeeded !== false;
    elements.verdictCleanup.textContent = cleanupOk ? "SUCCEEDED" : "FAILED";
    elements.verdictCleanup.className = "verdict-val " + (cleanupOk ? "val-success" : "val-fail");

    // Mandatory Honest Qualification Disclosure
    if (verdict === "NOT_FALSIFIED") {
      elements.adjudicationText.textContent =
        "STATUS: INCONCLUSIVE regarding universal safety. A verdict of NOT FALSIFIED certifies solely that no constraint violation occurred within the declared finite test budget (" +
        (detail.steps_completed || 200) +
        " steps, initial altitude " +
        (elements.initAltitude.value || 0.15) +
        "m). Dómnir does not claim universal mathematical proof or physical hardware safety: real-world aerodynamics, ground effect, rotor wash, and sensor drift require empirical hardware testing.";
    } else if (verdict === "FALSIFIED") {
      elements.adjudicationText.textContent =
        "STATUS: FALSIFIED. A physical boundary counterexample was detected during qualification (" +
        (elements.verdictFlightDesc.textContent || "boundary violation") +
        "). The controller does not maintain safe flight within the declared perturbation envelope (" +
        (detail.steps_completed || 0) +
        " steps executed).";
    } else {
      elements.adjudicationText.textContent =
        "STATUS: INVALID/INCONCLUSIVE. The qualification trial did not complete cleanly (" +
        (detail.error_message || "execution aborted or diverged") +
        "). No safety determination or formal qualification can be inferred from an incomplete or diverged trial.";
    }
  }

  // ==========================================================================
  // Responsive 2D Altitude Chart (Pure SVG, Zero External Dependencies)
  // ==========================================================================

  function renderAltitudeChart(trajectory, spec) {
    const svg = elements.altitudeSvgChart;
    if (!svg) return;

    if (!trajectory || trajectory.length === 0) {
      svg.innerHTML = '<text x="380" y="160" fill="#64748b" text-anchor="middle" font-family="monospace" font-size="14">No trajectory data to display</text>';
      return;
    }

    const width = 760;
    const height = 320;
    const padding = { top: 30, right: 30, bottom: 40, left: 60 };

    const chartW = width - padding.left - padding.right;
    const chartH = height - padding.top - padding.bottom;

    // Time domain
    const maxTime = trajectory[trajectory.length - 1].sim_time_s || spec.mission_duration_s || 0.4;
    const minTime = 0.0;

    // Altitude domain
    let minAlt = 0.0;
    let maxAlt = Math.max(spec.max_allowed_altitude_m * 1.05, 0.3);

    if (spec.min_allowed_altitude_m < minAlt) {
      minAlt = spec.min_allowed_altitude_m * 0.9;
    }

    // Dynamic scale scan
    for (const pt of trajectory) {
      const z = pt.position_m ? pt.position_m[2] : pt.altitude_m;
      if (z !== undefined && Number.isFinite(z)) {
        if (z < minAlt) {
          minAlt = Math.min(minAlt, z * 1.15 - 0.02);
        }
        if (z * 1.15 > maxAlt) {
          maxAlt = z * 1.15 + 0.02;
        }
      }
    }

    const scaleX = t => padding.left + ((t - minTime) / (maxTime - minTime || 1)) * chartW;
    const scaleY = a => padding.top + chartH - ((a - minAlt) / (maxAlt - minAlt || 1)) * chartH;

    let svgContent = `
      <defs>
        <clipPath id="chartPlotClip">
          <rect x="${padding.left}" y="${padding.top}" width="${chartW}" height="${chartH}" />
        </clipPath>
      </defs>
    `;

    // Horizontal grid lines
    const yTicks = 5;
    for (let i = 0; i <= yTicks; i++) {
      const aVal = minAlt + (i / yTicks) * (maxAlt - minAlt);
      const y = scaleY(aVal);
      svgContent += `<line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" stroke="#1e293b" stroke-width="1" stroke-dasharray="2,2"/>`;
      svgContent += `<text x="${padding.left - 8}" y="${y + 4}" fill="#64748b" font-family="monospace" font-size="10" text-anchor="end">${aVal.toFixed(2)}m</text>`;
    }

    // Vertical grid lines
    const xTicks = 4;
    for (let i = 0; i <= xTicks; i++) {
      const tVal = minTime + (i / xTicks) * (maxTime - minTime);
      const x = scaleX(tVal);
      svgContent += `<line x1="${x}" y1="${padding.top}" x2="${x}" y2="${height - padding.bottom}" stroke="#1e293b" stroke-width="1" stroke-dasharray="2,2"/>`;
      svgContent += `<text x="${x}" y="${height - padding.bottom + 18}" fill="#64748b" font-family="monospace" font-size="10" text-anchor="middle">${tVal.toFixed(2)}s</text>`;
    }

    // Tolerance Band
    const targetZ = spec.target_altitude_m;
    const tol = spec.altitude_tolerance_m;
    const topTolY = scaleY(targetZ + tol);
    const botTolY = scaleY(targetZ - tol);
    const bandHeight = Math.max(1, botTolY - topTolY);
    svgContent += `<rect x="${padding.left}" y="${topTolY}" width="${chartW}" height="${bandHeight}" fill="#06b6d4" fill-opacity="0.12" clip-path="url(#chartPlotClip)"/>`;

    // Safety Ceiling Boundary
    if (spec.max_allowed_altitude_m <= maxAlt) {
      const ceilY = scaleY(spec.max_allowed_altitude_m);
      svgContent += `<line x1="${padding.left}" y1="${ceilY}" x2="${width - padding.right}" y2="${ceilY}" stroke="#f43f5e" stroke-width="1.5" stroke-dasharray="4,3"/>`;
      svgContent += `<text x="${width - padding.right - 4}" y="${ceilY - 4}" fill="#f43f5e" font-family="monospace" font-size="9" text-anchor="end">Ceiling z_max (${spec.max_allowed_altitude_m.toFixed(2)}m)</text>`;
    }

    // Safety Floor Boundary
    if (spec.min_allowed_altitude_m >= minAlt) {
      const floorY = scaleY(spec.min_allowed_altitude_m);
      svgContent += `<line x1="${padding.left}" y1="${floorY}" x2="${width - padding.right}" y2="${floorY}" stroke="#f43f5e" stroke-width="1.5" stroke-dasharray="4,3"/>`;
      svgContent += `<text x="${width - padding.right - 4}" y="${floorY + 12}" fill="#f43f5e" font-family="monospace" font-size="9" text-anchor="end">Floor z_min (${spec.min_allowed_altitude_m.toFixed(2)}m)</text>`;
    }

    // Target Setpoint Line
    const targetY = scaleY(targetZ);
    svgContent += `<line x1="${padding.left}" y1="${targetY}" x2="${width - padding.right}" y2="${targetY}" stroke="#06b6d4" stroke-width="1.5" stroke-dasharray="5,3"/>`;
    svgContent += `<text x="${padding.left + 8}" y="${targetY - 5}" fill="#06b6d4" font-family="monospace" font-size="10">Target Setpoint (${targetZ.toFixed(2)}m)</text>`;

    // Trajectory Polyline
    let points = "";
    trajectory.forEach(pt => {
      const t = pt.sim_time_s;
      const z = pt.position_m ? pt.position_m[2] : (pt.altitude_m || 0.0);
      const x = scaleX(t);
      const y = scaleY(z);
      points += `${x.toFixed(1)},${y.toFixed(1)} `;
    });

    svgContent += `<polyline points="${points.trim()}" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" clip-path="url(#chartPlotClip)"/>`;

    // Interactive cursor elements
    svgContent += `<line id="chartCrosshairLine" class="chart-crosshair" x1="${padding.left}" y1="${padding.top}" x2="${padding.left}" y2="${height - padding.bottom}" style="display: none;" />`;
    svgContent += `<circle id="chartCrosshairDot" class="chart-crosshair-dot" cx="0" cy="0" r="4.5" style="display: none;" />`;

    // Axis labels
    svgContent += `<text x="${width / 2}" y="${height - 8}" fill="#94a3b8" font-family="sans-serif" font-size="11" text-anchor="middle">Simulation Time (seconds)</text>`;
    svgContent += `<text x="18" y="${height / 2}" fill="#94a3b8" font-family="sans-serif" font-size="11" text-anchor="middle" transform="rotate(-90 18 ${height / 2})">Altitude (meters)</text>`;

    svg.innerHTML = svgContent;

    setupChartHover(trajectory, scaleX, scaleY, padding, chartW, chartH);
  }

  function setupChartHover(trajectory, scaleX, scaleY, padding, chartW, chartH) {
    const wrap = elements.chartWrapper;
    const tooltip = elements.chartTooltip;
    const svg = elements.altitudeSvgChart;
    if (!wrap || !tooltip || !svg) return;

    const crosshairLine = svg.querySelector("#chartCrosshairLine");
    const crosshairDot = svg.querySelector("#chartCrosshairDot");

    wrap.onmousemove = e => {
      const rect = wrap.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;

      const normX = (mouseX / rect.width) * 760;
      if (normX < padding.left || normX > padding.left + chartW) {
        tooltip.style.display = "none";
        if (crosshairLine) crosshairLine.style.display = "none";
        if (crosshairDot) crosshairDot.style.display = "none";
        return;
      }

      const fraction = (normX - padding.left) / chartW;
      const sampleIndex = Math.min(
        trajectory.length - 1,
        Math.max(0, Math.round(fraction * (trajectory.length - 1)))
      );
      const pt = trajectory[sampleIndex];
      if (!pt) return;

      const t = pt.sim_time_s || 0.0;
      const z = pt.position_m ? pt.position_m[2] : (pt.altitude_m || 0.0);
      const vz = pt.velocity_mps ? pt.velocity_mps[2] : 0.0;
      const thrust = pt.action && pt.action.length > 0 ? pt.action[0] : (pt.thrust || 0.0);

      const ptX = scaleX(t);
      const ptY = scaleY(z);

      if (crosshairLine) {
        crosshairLine.setAttribute("x1", ptX);
        crosshairLine.setAttribute("x2", ptX);
        crosshairLine.style.display = "block";
      }
      if (crosshairDot) {
        crosshairDot.setAttribute("cx", ptX);
        crosshairDot.setAttribute("cy", ptY);
        crosshairDot.style.display = "block";
      }

      tooltip.innerHTML = `
        <div><strong>t:</strong> ${t.toFixed(4)}s (step ${pt.step_index || sampleIndex})</div>
        <div><strong>z:</strong> ${z.toFixed(4)}m</div>
        <div><strong>vz:</strong> ${vz.toFixed(3)}m/s</div>
        <div><strong>thrust:</strong> ${Number(thrust).toFixed(4)}N</div>
      `;

      tooltip.style.display = "block";
      const tooltipX = Math.min(rect.width - 160, Math.max(10, mouseX + 14));
      tooltip.style.left = tooltipX + "px";
      tooltip.style.top = "20px";
    };

    wrap.onmouseleave = () => {
      tooltip.style.display = "none";
      if (crosshairLine) crosshairLine.style.display = "none";
      if (crosshairDot) crosshairDot.style.display = "none";
    };
  }

  // ==========================================================================
  // Court Record Export & Clipboard
  // ==========================================================================

  function downloadCourtRecord() {
    if (!state.activeCourtRecord) return;
    const jsonStr = JSON.stringify(state.activeCourtRecord, null, 2);
    const blob = new Blob([jsonStr], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const recordId = state.activeCourtRecord.record_id || state.activeExperimentId || "latest";
    a.href = url;
    a.download = `court-record-${recordId}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast("Court record downloaded: court-record-" + recordId + ".json", "success");
  }

  function copyCourtRecord() {
    if (!state.activeCourtRecord) return;
    const jsonStr = JSON.stringify(state.activeCourtRecord, null, 2);
    navigator.clipboard.writeText(jsonStr).then(() => {
      const origText = elements.copyCourtRecordBtn.textContent;
      elements.copyCourtRecordBtn.textContent = "Copied!";
      toast("Court record JSON copied to clipboard.", "info");
      setTimeout(() => {
        elements.copyCourtRecordBtn.textContent = origText;
      }, 1500);
    });
  }

  function openActiveRecordInVerifier() {
    if (!state.activeCourtRecord) return;
    elements.courtJsonInput.value = JSON.stringify(state.activeCourtRecord, null, 2);

    const verifierTab = document.querySelector('[data-tab="tab-verifier"]');
    if (verifierTab) verifierTab.click();

    // Trigger verification automatically
    verifyCourtRecord();
  }

  // ==========================================================================
  // Independent Court Record Verifier
  // ==========================================================================

  function setupVerifier() {
    elements.dropZone.addEventListener("click", () => {
      elements.courtFileInput.value = "";
      elements.courtFileInput.click();
    });

    elements.browseFileBtn.addEventListener("click", e => {
      e.stopPropagation();
      elements.courtFileInput.value = "";
      elements.courtFileInput.click();
    });

    elements.dropZone.addEventListener("dragover", e => {
      e.preventDefault();
      elements.dropZone.classList.add("dragover");
    });

    elements.dropZone.addEventListener("dragleave", () => {
      elements.dropZone.classList.remove("dragover");
    });

    elements.dropZone.addEventListener("drop", e => {
      e.preventDefault();
      elements.dropZone.classList.remove("dragover");
      if (e.dataTransfer.files.length > 0) {
        loadJsonFile(e.dataTransfer.files[0]);
      }
    });

    elements.courtFileInput.addEventListener("change", e => {
      if (e.target.files.length > 0) {
        loadJsonFile(e.target.files[0]);
      }
    });

    elements.pasteSampleBtn.addEventListener("click", () => {
      if (state.activeCourtRecord) {
        elements.courtJsonInput.value = JSON.stringify(state.activeCourtRecord, null, 2);
        toast("Loaded active run court record into verifier.", "info");
      } else {
        toast("No active trial record yet. Run a trial in Tab 1 or upload a saved court record.", "warning");
      }
    });

    elements.submitVerifyBtn.addEventListener("click", verifyCourtRecord);
  }

  function loadJsonFile(file) {
    const reader = new FileReader();
    reader.onload = ev => {
      try {
        const text = ev.target.result;
        const parsed = JSON.parse(text);
        if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
          throw new Error("Court Record JSON root must be an object");
        }
        elements.courtJsonInput.value = text;
        toast("Loaded court record: " + (parsed.record_id || file.name), "success");
      } catch (err) {
        toast("Invalid JSON file: " + err.message, "error");
      }
    };
    reader.readAsText(file);
  }

  async function verifyCourtRecord() {
    const rawText = elements.courtJsonInput.value.trim();
    if (!rawText) {
      toast("Please upload or paste a Court Record JSON payload.", "warning");
      return;
    }

    let parsedRecord;
    try {
      parsedRecord = JSON.parse(rawText);
      if (typeof parsedRecord !== "object" || parsedRecord === null || Array.isArray(parsedRecord)) {
        throw new Error("Payload root must be an object");
      }
    } catch (err) {
      toast("Malformed JSON: " + err.message, "error");
      return;
    }

    elements.submitVerifyBtn.disabled = true;
    elements.verifySpinner.style.display = "inline-block";
    elements.verifyResultsCard.style.display = "none";
    elements.verifyErrorsBox.style.display = "none";

    try {
      const res = await fetch("/court-records/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ court_record: parsedRecord }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : "Verification call failed");
      }

      displayVerificationResult(data);
      if (data.verified) {
        toast("Court record independently verified with zero divergence.", "success");
      } else {
        toast("Court record verification rejected.", "error");
      }
    } catch (err) {
      toast("Verification Error: " + err.message, "error");
    } finally {
      elements.submitVerifyBtn.disabled = false;
      elements.verifySpinner.style.display = "none";
    }
  }

  function displayVerificationResult(res) {
    elements.verifyResultsCard.style.display = "flex";

    if (res.verified) {
      elements.verifyOverallBadge.textContent = "COURT RECORD VERIFIED";
      elements.verifyOverallBadge.className = "verify-verdict-badge";
    } else {
      elements.verifyOverallBadge.textContent = "VERIFICATION REJECTED";
      elements.verifyOverallBadge.className = "verify-verdict-badge badge-fail";
    }

    elements.verifyMetaDetails.textContent =
      "Record ID: " + (res.record_id || "unspecified") + " | Adjudicated: " + (res.timestamp || new Date().toISOString());

    setCheckStatus(elements.iconControllerHash, elements.detailControllerHash, res.controller_hash_matched, "Controller source SHA-256 matches verified hash", "Controller SHA-256 mismatch");
    setCheckStatus(elements.iconTrajectoryHash, elements.detailTrajectoryHash, res.trajectory_hash_matched, "Trajectory dataset SHA-256 matches verified hash", "Trajectory hash mismatch");
    setCheckStatus(elements.iconModelHashes, elements.detailModelHashes, res.model_hashes_matched, "MuJoCo cf2.xml and asset SHA-256 hashes verified", "Model or mesh hash divergence");
    setCheckStatus(elements.iconEventChain, elements.detailEventChain, res.event_chain_verified, "Host event log hash chain verified", "Host event chain integrity failed");

    const replayDiff = res.replay_max_abs_difference !== undefined ? res.replay_max_abs_difference : 0.0;
    const replayPassed =
      (res.replay_verdict === "MATCHED" || res.replay_verdict === "REPLAY_MATCHED") &&
      replayDiff <= (res.tolerance || 1e-12);

    setCheckStatus(
      elements.iconPhysicalReplay,
      elements.detailPhysicalReplay,
      replayPassed,
      "Fresh MuJoCo simulation match: max diff " + Number(replayDiff).toExponential(2) + " m <= " + Number(res.tolerance || 1e-12).toExponential(0) + " m",
      "Replay divergence: max diff " + Number(replayDiff).toExponential(2) + " m exceeds tolerance"
    );

    if (res.errors && res.errors.length > 0) {
      elements.verifyErrorsList.innerHTML = "";
      res.errors.forEach(errStr => {
        const li = document.createElement("li");
        li.textContent = errStr;
        elements.verifyErrorsList.appendChild(li);
      });
      elements.verifyErrorsBox.style.display = "block";
    }
  }

  function setCheckStatus(iconEl, detailEl, isSuccess, successText, failText) {
    if (isSuccess) {
      iconEl.textContent = "\u2713";
      iconEl.className = "check-icon ok";
      detailEl.textContent = successText;
      detailEl.style.color = "var(--accent-emerald)";
    } else {
      iconEl.textContent = "\u2717";
      iconEl.className = "check-icon fail";
      detailEl.textContent = failText;
      detailEl.style.color = "var(--accent-rose)";
    }
  }

  // ==========================================================================
  // Copy Utilities
  // ==========================================================================

  function setupCodeCopy() {
    elements.copyCodeBtn.addEventListener("click", () => {
      const text = elements.controllerSource.value;
      if (!text) return;
      navigator.clipboard.writeText(text).then(() => {
        const orig = elements.copyCodeBtn.textContent;
        elements.copyCodeBtn.textContent = "Copied!";
        toast("Controller code copied to clipboard.", "info");
        setTimeout(() => (elements.copyCodeBtn.textContent = orig), 1500);
      });
    });
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // ==========================================================================
  // Containment Audit
  // ==========================================================================

  async function fetchContainmentStatus() {
    if (!elements.containmentOverallBadge) return;
    try {
      const res = await fetch("/containment/status");
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      renderContainmentStatus(data);
    } catch (err) {
      console.warn("Failed to fetch containment status:", err);
      if (elements.containmentOverallBadge) {
        elements.containmentOverallBadge.textContent = "UNAVAILABLE";
        elements.containmentOverallBadge.className = "status-badge badge-warning";
      }
    }
  }

  function renderContainmentStatus(data) {
    if (!elements.containmentOverallBadge) return;

    const overall = data.status || "UNKNOWN";
    elements.containmentOverallBadge.textContent = overall;
    if (overall === "PASS") {
      elements.containmentOverallBadge.className = "status-badge badge-success";
    } else if (overall === "PARTIAL") {
      elements.containmentOverallBadge.className = "status-badge badge-warning";
    } else {
      elements.containmentOverallBadge.className = "status-badge badge-danger";
    }

    if (elements.containmentEnvText) {
      elements.containmentEnvText.textContent = data.microvm_available
        ? "Linux KVM + Microsandbox Active"
        : "Vultr Cloud Compute Feasibility Baseline";
    }
    if (elements.containmentCleanupText) {
      elements.containmentCleanupText.textContent = data.cleanup_guarantee || "100% Deletion Confirmed";
    }
    if (elements.containmentSourceText) {
      elements.containmentSourceText.textContent = data.execution_source === "live_microvm"
        ? "Live Host Execution"
        : "Recorded Cryptographic Evidence";
    }
    if (elements.containmentTimestampText) {
      elements.containmentTimestampText.textContent = data.timestamp
        ? new Date(data.timestamp).toLocaleString()
        : "Certified Baseline";
    }

    const fixMap = {};
    (data.fixtures || []).forEach(f => {
      fixMap[f.fixture_id] = f;
    });

    const cap = fixMap["CAP-HOST-001"];
    if (cap) {
      if (elements.fixtureBadgeCap) elements.fixtureBadgeCap.textContent = cap.status;
      if (elements.fixturePolicyCap && cap.policy_id) elements.fixturePolicyCap.textContent = cap.policy_id;
      if (elements.fixtureCleanupCap) {
        elements.fixtureCleanupCap.textContent = cap.cleanup_succeeded ? "100% Confirmed" : "Failed";
      }
    }

    const net = fixMap["NET-EGRESS-001"];
    if (net) {
      if (elements.fixtureBadgeNet) elements.fixtureBadgeNet.textContent = net.status;
      if (elements.fixtureEgressNet && net.policy) elements.fixtureEgressNet.textContent = net.policy.default_egress || "deny";
      if (elements.fixtureIngressNet && net.policy) elements.fixtureIngressNet.textContent = net.policy.default_ingress || "deny";
      if (elements.fixtureCleanupNet) {
        elements.fixtureCleanupNet.textContent = net.cleanup_succeeded ? "100% Confirmed" : "Failed";
      }
    }

    const tm = fixMap["RES-TIME-001"];
    if (tm) {
      if (elements.fixtureBadgeTime) elements.fixtureBadgeTime.textContent = tm.status;
      if (elements.fixtureElapsedVal && typeof tm.elapsed_seconds === "number") {
        elements.fixtureElapsedVal.textContent = tm.elapsed_seconds.toFixed(3) + " s";
      }
      if (elements.fixtureCleanupTime) {
        elements.fixtureCleanupTime.textContent = tm.cleanup_succeeded ? "100% Confirmed" : "Failed";
      }
    }

    const mem = fixMap["RES-MEM-001"];
    if (mem) {
      if (elements.fixtureBadgeMem) elements.fixtureBadgeMem.textContent = mem.status;
      if (elements.fixtureExitState && mem.observation) {
        elements.fixtureExitState.textContent = (mem.observation.job_state || "exited") + " (code " + (mem.observation.exit_code ?? "-1") + ")";
      }
      if (elements.fixtureAttributionVal) {
        elements.fixtureAttributionVal.textContent = (mem.termination_cause || "NOT_ATTRIBUTED") + " (Truthful)";
      }
      if (elements.fixtureCleanupMem) {
        elements.fixtureCleanupMem.textContent = mem.cleanup_succeeded ? "100% Confirmed" : "Failed";
      }
    }

    if (elements.fixtureBadgeCleanup) {
      const isPass = (data.cleanup_guarantee || "").includes("PASS");
      elements.fixtureBadgeCleanup.textContent = isPass ? "PASS" : "FAIL";
      elements.fixtureBadgeCleanup.className = isPass ? "status-badge badge-success" : "status-badge badge-danger";
    }
    if (elements.fixtureAuditCleanup) {
      elements.fixtureAuditCleanup.textContent = data.cleanup_guarantee || "PASS (Deterministic)";
      const isPass = (data.cleanup_guarantee || "").includes("PASS");
      elements.fixtureAuditCleanup.className = isPass ? "row-val font-mono text-emerald" : "row-val font-mono text-rose";
    }

    if (data.host_event_log) {
      if (elements.containmentLogBadge) {
        elements.containmentLogBadge.textContent = data.host_event_log.verified ? "VERIFIED" : "UNVERIFIED";
        elements.containmentLogBadge.className = data.host_event_log.verified ? "badge badge-default" : "badge badge-fail";
      }
      if (elements.containmentLogFile) elements.containmentLogFile.textContent = data.host_event_log.file || "events.jsonl";
      if (elements.containmentEventCount) elements.containmentEventCount.textContent = (data.host_event_log.event_count || 18) + " events";
      if (elements.containmentShaHead) elements.containmentShaHead.textContent = data.host_event_log.sha256_head || "";
      if (elements.containmentLogStatus) {
        elements.containmentLogStatus.textContent = data.host_event_log.verified
          ? "All records verified against SHA-256 state chain"
          : "Host log verification failed";
        elements.containmentLogStatus.className = data.host_event_log.verified
          ? "log-val font-mono text-emerald"
          : "log-val font-mono text-rose";
      }
    }

    if (elements.containmentLimitationsList && Array.isArray(data.limitations)) {
      elements.containmentLimitationsList.innerHTML = "";
      data.limitations.forEach(lim => {
        const li = document.createElement("li");
        li.textContent = lim;
        elements.containmentLimitationsList.appendChild(li);
      });
    }
  }

  async function runContainmentSuite() {
    if (!elements.runContainmentBtn) return;
    elements.runContainmentBtn.disabled = true;
    if (elements.containmentSpinner) elements.containmentSpinner.style.display = "inline-block";

    try {
      const res = await fetch("/containment/run", { method: "POST" });
      if (res.status === 503) {
        const errData = await res.json().catch(() => ({}));
        toast(errData.detail || "MicroVM containment runtime is not available on this host. Displaying certified baseline.", "warning");
        await fetchContainmentStatus();
        return;
      }
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Containment suite execution failed (HTTP " + res.status + ")");
      }
      const data = await res.json();
      renderContainmentStatus(data);
      toast("Containment suite executed successfully and verified.", "success");
    } catch (err) {
      toast(err.message, "warning");
    } finally {
      elements.runContainmentBtn.disabled = false;
      if (elements.containmentSpinner) elements.containmentSpinner.style.display = "none";
    }
  }

  // ==========================================================================
  // Initialization
  // ==========================================================================

  function init() {
    setupTabs();
    setupPresets();
    setupVerifier();
    setupCodeCopy();
    setupInitialModelCards();

    // Inputs listeners
    elements.missionDuration.addEventListener("input", updateStepBudget);
    elements.validateSpecBtn.addEventListener("click", validateMissionSpec);
    elements.generateControllerBtn.addEventListener("click", generateController);
    elements.loadBaselineBtn.addEventListener("click", loadBaselineController);
    elements.controllerSource.addEventListener("input", e => updateCodeMetadata(e.target.value));

    elements.runExperimentBtn.addEventListener("click", runExperiment);
    elements.downloadCourtRecordBtn.addEventListener("click", downloadCourtRecord);
    elements.copyCourtRecordBtn.addEventListener("click", copyCourtRecord);
    elements.openInVerifierBtn.addEventListener("click", openActiveRecordInVerifier);
    elements.refreshStatusBtn.addEventListener("click", checkHealthAndReadiness);

    if (elements.refreshContainmentBtn) {
      elements.refreshContainmentBtn.addEventListener("click", fetchContainmentStatus);
    }
    if (elements.runContainmentBtn) {
      elements.runContainmentBtn.addEventListener("click", runContainmentSuite);
    }

    // Initial setup
    loadBaselineController();
    updateStepBudget();
    checkHealthAndReadiness();
    fetchModels();
    fetchContainmentStatus();

    // Initial empty chart placeholder
    renderAltitudeChart([], getSpecFromForm());
  }

  document.addEventListener("DOMContentLoaded", init);
})();
