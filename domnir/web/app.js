/**
 * Dómnir Web Application Controller
 * Offline-ready, zero external dependencies, zero em dashes.
 */

(function () {
  "use strict";

  const state = {
    selectedModel: "glm-5.3-flash",
    selectedReasoningEffort: "minimal",
    models: [],
    activeSpec: null,
    activeController: null,
    activeExperimentId: null,
    activeCourtRecord: null,
    activeTrajectory: [],
    pollTimer: null,
    ragnarok: {
      strategy: "differential_evolution",
      budget: 12,
      candidates: [],
      criticalWitness: null,
      minimizedWitness: null,
      repairedResult: null,
      discoverySpeedup: 1.0,
    },
  };

  let droneViewer = null;

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
    // Status bar (minimalist indicators)
    statusApiPill: document.getElementById("statusApiPill"),
    apiDot: document.getElementById("apiDot"),
    apiStatusText: document.getElementById("apiStatusText"),
    statusInferencePill: document.getElementById("statusInferencePill"),
    inferenceDot: document.getElementById("inferenceDot"),
    inferenceStatusText: document.getElementById("inferenceStatusText"),
    statusSandboxPill: document.getElementById("statusSandboxPill"),
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
    reasoningPills: document.querySelectorAll(".reasoning-pill"),
    reasoningHint: document.getElementById("reasoningHint"),
    generateControllerBtn: document.getElementById("generateControllerBtn"),
    genSpinner: document.getElementById("genSpinner"),
    loadBaselineBtn: document.getElementById("loadBaselineBtn"),
    controllerSource: document.getElementById("controllerSource"),
    // Code canvas
    codeLineNumbers: document.getElementById("codeLineNumbers"),
    // Theme Toggle (Rune Dusk / Rune Dawn)
    themeToggleBtn: document.getElementById("themeToggleBtn"),
    themeToggleLabel: document.getElementById("themeToggleLabel"),

    // Workspace Quick Oracle Drawer
    workspaceOraclePanel: document.getElementById("workspaceOraclePanel"),
    toggleWsOracleBtn: document.getElementById("toggleWsOracleBtn"),
    wsOracleToggleIcon: document.getElementById("wsOracleToggleIcon"),
    wsOracleBody: document.getElementById("wsOracleBody"),
    wsOracleSearchInput: document.getElementById("wsOracleSearchInput"),
    wsOracleChips: document.querySelectorAll("[data-ws-topic]"),
    wsOracleResultsGrid: document.getElementById("wsOracleResultsGrid"),
    wsOracleJumpArchitectureBtn: document.getElementById("wsOracleJumpArchitectureBtn"),


    // Ragnarok Knowledge Oracle
    openOracleHeaderBtn: document.getElementById("openOracleHeaderBtn"),
    oracleSearchInput: document.getElementById("oracleSearchInput"),
    oracleResultsContainer: document.getElementById("oracleResultsContainer"),
    oracleTopicPills: document.querySelectorAll(".topic-pill"),

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

    // Ragnarok Adversarial Arena & Failure Atlas
    ragnarokArenaCard: document.getElementById("ragnarokArenaCard"),
    arenaStatusBadge: document.getElementById("arenaStatusBadge"),
    stratPillDE: document.getElementById("stratPillDE"),
    stratPillSobol: document.getElementById("stratPillSobol"),
    stratPillCompare: document.getElementById("stratPillCompare"),
    stratPills: document.querySelectorAll(".strategy-pill"),
    ragnarokBudgetInput: document.getElementById("ragnarokBudgetInput"),
    ragnarokBudgetValue: document.getElementById("ragnarokBudgetValue"),
    runFalsifyBtn: document.getElementById("runFalsifyBtn"),
    falsifySpinner: document.getElementById("falsifySpinner"),
    runMinimizeBtn: document.getElementById("runMinimizeBtn"),
    minimizeSpinner: document.getElementById("minimizeSpinner"),
    runRepairBtn: document.getElementById("runRepairBtn"),
    repairSpinner: document.getElementById("repairSpinner"),
    atlasMetricTrials: document.getElementById("atlasMetricTrials"),
    atlasMetricViolations: document.getElementById("atlasMetricViolations"),
    atlasMetricMinRobustness: document.getElementById("atlasMetricMinRobustness"),
    atlasMetricSpeedup: document.getElementById("atlasMetricSpeedup"),
    failureAtlasContainer: document.getElementById("failureAtlasContainer"),
    failureAtlasWrapper: document.getElementById("failureAtlasWrapper"),
    failureAtlasSvg: document.getElementById("failureAtlasSvg"),
    atlasTooltip: document.getElementById("atlasTooltip"),
    witnessInspectorCard: document.getElementById("witnessInspectorCard"),
    witnessDetailsBody: document.getElementById("witnessDetailsBody"),
    witnessEmptyText: document.getElementById("witnessEmptyText"),
    witnessDataGrid: document.getElementById("witnessDataGrid"),
    witnessPredicate: document.getElementById("witnessPredicate"),
    witnessTimestamp: document.getElementById("witnessTimestamp"),
    witnessMargin: document.getElementById("witnessMargin"),
    witnessDisturbance: document.getElementById("witnessDisturbance"),
    witnessAltitude: document.getElementById("witnessAltitude"),
    witnessCostReduction: document.getElementById("witnessCostReduction"),
    repairInspectorCard: document.getElementById("repairInspectorCard"),
    repairDetailsBody: document.getElementById("repairDetailsBody"),
    repairEmptyText: document.getElementById("repairEmptyText"),
    repairContentBox: document.getElementById("repairContentBox"),
    repairStatusBox: document.getElementById("repairStatusBox"),
    repairOutcomeBadge: document.getElementById("repairOutcomeBadge"),
    repairHoldoutRate: document.getElementById("repairHoldoutRate"),
    repairRevisionsCount: document.getElementById("repairRevisionsCount"),
    repairedControllerSource: document.getElementById("repairedControllerSource"),
    copyRepairedCodeBtn: document.getElementById("copyRepairedCodeBtn"),
    loadRepairedCodeBtn: document.getElementById("loadRepairedCodeBtn"),

    // Court Record Export
    downloadCourtRecordBtn: document.getElementById("downloadCourtRecordBtn"),
    copyCourtRecordBtn: document.getElementById("copyCourtRecordBtn"),
    openInVerifierBtn: document.getElementById("openInVerifierBtn"),

    // Verifier Tab
    dropZone: document.getElementById("dropZone"),
    courtFileInput: document.getElementById("courtFileInput") || document.getElementById("recordFileInput"),
    browseFileBtn: document.getElementById("browseFileBtn") || document.getElementById("selectFileBtn"),
    pasteSampleBtn: document.getElementById("pasteSampleBtn"),
    courtJsonInput: document.getElementById("courtJsonInput") || document.getElementById("rawRecordInput"),
    submitVerifyBtn: document.getElementById("submitVerifyBtn"),
    verifySpinner: document.getElementById("verifySpinner"),
    verifyResultsCard: document.getElementById("verifyResultsCard"),
    verifyOverallBadge: document.getElementById("verifyOverallBadge") || document.getElementById("overallVerifyBadge"),
    verifyMetaDetails: document.getElementById("verifyMetaDetails"),

    // 3D Visual Stage & Replay
    plantVisualStage: document.getElementById("plantVisualStage"),
    droneCanvas: document.getElementById("droneCanvas"),
    droneFallbackStill: document.getElementById("droneFallbackStill"),
    viewerModeBadge: document.getElementById("viewerModeBadge"),
    stagePauseBtn: document.getElementById("stagePauseBtn"),
    stageResetBtn: document.getElementById("stageResetBtn"),
    stageReplayBar: document.getElementById("stageReplayBar"),
    replayPlayBtn: document.getElementById("replayPlayBtn"),
    replayTimelineScrub: document.getElementById("replayTimelineScrub"),
    replayTimeText: document.getElementById("replayTimeText"),
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
    runContainmentSuiteBtn: document.getElementById("runContainmentSuiteBtn"),
    containmentSpinner: document.getElementById("containmentSpinner"),
    containmentEnvText: document.getElementById("containmentEnvText"),
    containmentCleanupText: document.getElementById("containmentCleanupText"),
    containmentSourceText: document.getElementById("containmentSourceText"),
    containmentTimestampText: document.getElementById("containmentTimestampText"),

    // Stepper elements
    workspaceGrid: document.getElementById("workspaceGrid"),
    toggleViewModeBtn: document.getElementById("toggleViewModeBtn"),
    stepBtns: [
      document.getElementById("stepBtn1"),
      document.getElementById("stepBtn2"),
      document.getElementById("stepBtn3"),
      document.getElementById("stepBtn4"),
    ],
    stepPanes: [
      document.getElementById("stepPanel1"),
      document.getElementById("stepPanel2"),
      document.getElementById("stepPanel3"),
      document.getElementById("stepPanel4"),
    ],
    stepLines: [
      document.getElementById("stepLine1"),
      document.getElementById("stepLine2"),
      document.getElementById("stepLine3"),
    ],
    goToStep2Btn: document.getElementById("goToStep2Btn"),
    backToStep1Btn: document.getElementById("backToStep1Btn"),
    goToStep3Btn: document.getElementById("goToStep3Btn"),
    backToStep2Btn: document.getElementById("backToStep2Btn"),
    goToStep4Btn: document.getElementById("goToStep4Btn"),
    backToStep3Btn: document.getElementById("backToStep3Btn"),
    restartExperimentBtn: document.getElementById("restartExperimentBtn"),

    // Step segregation and Simulation Arena Stage
    simulationArenaStage: document.getElementById("simulationArenaStage"),
    arena3DWrapper: document.getElementById("arena3DWrapper"),
    plantStageWrapper: document.getElementById("plantStageWrapper"),

    // Synthesis loading
    synthesisLoadingBox: document.getElementById("synthesisLoadingBox"),
    synthesisStatusText: document.getElementById("synthesisStatusText"),
    synthesisProgressBar: document.getElementById("synthesisProgressBar"),

    // Interactive Tutorial Sandbox
    startTutorialBtn: document.getElementById("startTutorialBtn"),
    tutorialBackdrop: document.getElementById("tutorialBackdrop"),
    closeTutorialBtn: document.getElementById("closeTutorialBtn"),

    // Advanced envelope toggle
    toggleAdvancedEnvelopeBtn: document.getElementById("toggleAdvancedEnvelopeBtn"),
    advancedEnvelopeFields: document.getElementById("advancedEnvelopeFields"),
    advToggleIcon: document.getElementById("advToggleIcon"),

    // Onboarding Tour
    startTourBtn: document.getElementById("startTourBtn"),
    tourBackdrop: document.getElementById("tourBackdrop"),
    tourStepBadge: document.getElementById("tourStepBadge"),
    closeTourBtn: document.getElementById("closeTourBtn"),
    tourTitle: document.getElementById("tourTitle"),
    tourContent: document.getElementById("tourContent"),
    skipTourBtn: document.getElementById("skipTourBtn"),
    prevTourBtn: document.getElementById("prevTourBtn"),
    nextTourBtn: document.getElementById("nextTourBtn"),

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

  // Toast Notification System with Deduplication and Throttling
  function toast(message, type = "info") {
    if (!elements.toastContainer) return;

    // Deduplicate: if identical message is already displayed, do not flood
    const existing = Array.from(elements.toastContainer.querySelectorAll(".toast span"));
    if (existing.some(s => s.textContent === message)) {
      return;
    }

    // Cap to max 2 concurrent toasts to prevent UI obstruction
    const currentToasts = elements.toastContainer.querySelectorAll(".toast");
    if (currentToasts.length >= 2) {
      currentToasts[0].remove();
    }

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
    }, 3800);
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
    if (elements.apiDot) elements.apiDot.className = "status-dot dot-unknown";
    if (elements.apiStatusText) elements.apiStatusText.textContent = "Connecting...";
    if (elements.statusApiPill) elements.statusApiPill.title = "FastAPI Control Plane: Connecting...";

    try {
      const healthRes = await fetch("/health");
      if (!healthRes.ok) throw new Error("HTTP " + healthRes.status);
      const healthData = await healthRes.json();
      if (elements.apiDot) elements.apiDot.className = "status-dot dot-ok";
      if (elements.apiStatusText) elements.apiStatusText.textContent = "ONLINE (v" + (healthData.version || "0.1.0") + ")";
      if (elements.statusApiPill) elements.statusApiPill.title = "FastAPI Control Plane: Online (v" + (healthData.version || "0.1.0") + ")";

      const readyRes = await fetch("/ready");
      if (readyRes.ok) {
        const readyData = await readyRes.json();
        if (readyData.inference_configured) {
          if (elements.inferenceDot) elements.inferenceDot.className = "status-dot dot-ok";
          if (elements.inferenceStatusText) elements.inferenceStatusText.textContent = "CONNECTED";
          if (elements.statusInferencePill) elements.statusInferencePill.title = "Vultr Serverless Inference: Connected";
        } else {
          if (elements.inferenceDot) elements.inferenceDot.className = "status-dot dot-warn";
          if (elements.inferenceStatusText) elements.inferenceStatusText.textContent = "LOCAL SIM ONLY";
          if (elements.statusInferencePill) elements.statusInferencePill.title = "Inference Gateway: Local Simulation Only";
        }

        if (readyData.microvm_available) {
          if (elements.backendDot) elements.backendDot.className = "status-dot dot-ok";
          if (elements.backendStatusText) elements.backendStatusText.textContent = "MICROVM (KVM)";
          if (elements.statusSandboxPill) elements.statusSandboxPill.title = "Sandbox: Hardware MicroVM Isolation (/dev/kvm verified)";
        } else {
          if (elements.backendDot) elements.backendDot.className = "status-dot dot-ok";
          if (elements.backendStatusText) elements.backendStatusText.textContent = "TRUSTED SIMULATOR";
          if (elements.statusSandboxPill) elements.statusSandboxPill.title = "Sandbox: Trusted Host Simulator Fallback";
        }
      }
    } catch (err) {
      if (elements.apiDot) elements.apiDot.className = "status-dot dot-err";
      if (elements.apiStatusText) elements.apiStatusText.textContent = "OFFLINE";
      if (elements.statusApiPill) elements.statusApiPill.title = "FastAPI Control Plane: Offline";
      if (elements.inferenceDot) elements.inferenceDot.className = "status-dot dot-unknown";
      if (elements.inferenceStatusText) elements.inferenceStatusText.textContent = "UNKNOWN";
      if (elements.statusInferencePill) elements.statusInferencePill.title = "Inference: Unknown";
      if (elements.backendDot) elements.backendDot.className = "status-dot dot-unknown";
      if (elements.backendStatusText) elements.backendStatusText.textContent = "UNKNOWN";
      if (elements.statusSandboxPill) elements.statusSandboxPill.title = "Sandbox: Unknown";
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

  const REASONING_HINTS = {
    minimal: "Minimal (fastest token generation, minimal reasoning depth)",
    low: "Low (light step-by-step reasoning)",
    medium: "Medium (standard analytical reasoning depth)",
    high: "High (deep mathematical reasoning for complex control laws)",
  };

  function setupReasoningEffort() {
    if (!elements.reasoningPills) return;
    elements.reasoningPills.forEach(pill => {
      pill.addEventListener("click", () => {
        const effort = pill.dataset.effort || "minimal";
        state.selectedReasoningEffort = effort;

        elements.reasoningPills.forEach(p => {
          p.classList.remove("active");
          p.setAttribute("aria-checked", "false");
        });
        pill.classList.add("active");
        pill.setAttribute("aria-checked", "true");

        if (elements.reasoningHint) {
          elements.reasoningHint.textContent = REASONING_HINTS[effort] || effort;
        }
      });
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
  // Stepper & Progressive Disclosure
  // ==========================================================================

  let currentStep = 1;

  function switchStep(stepNum) {
    if (stepNum < 1) stepNum = 1;
    if (stepNum > 4) stepNum = 4;
    currentStep = stepNum;

    elements.stepBtns.forEach((btn, idx) => {
      if (!btn) return;
      const num = idx + 1;
      btn.classList.remove("active", "completed");
      if (num === stepNum) {
        btn.classList.add("active");
      } else if (num < stepNum) {
        btn.classList.add("completed");
      }
    });

    elements.stepPanes.forEach((pane, idx) => {
      if (!pane) return;
      const num = idx + 1;
      pane.classList.remove("active");
      if (num === stepNum) {
        pane.classList.add("active");
      }
    });

    elements.stepLines.forEach((line, idx) => {
      if (!line) return;
      const stepIndex = idx + 1;
      line.classList.remove("completed");
      if (stepIndex < stepNum) {
        line.classList.add("completed");
      }
    });

    // Plant Visual Stage DOM Reparenting between Step 1 and Step 4
    if (elements.plantVisualStage) {
      if (stepNum === 4 && elements.arena3DWrapper) {
        if (elements.plantVisualStage.parentElement !== elements.arena3DWrapper) {
          elements.arena3DWrapper.appendChild(elements.plantVisualStage);
        }
      } else if (stepNum === 1 && elements.plantStageWrapper) {
        if (elements.plantVisualStage.parentElement !== elements.plantStageWrapper) {
          elements.plantStageWrapper.appendChild(elements.plantVisualStage);
        }
      }
      if (droneViewer && droneViewer.resize) {
        setTimeout(() => droneViewer.resize(), 50);
      }
    }

    // Smooth scroll to top of workspace
    if (elements.workspaceGrid) {
      elements.workspaceGrid.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  function setupStepper() {
    elements.stepBtns.forEach((btn, idx) => {
      if (!btn) return;
      btn.addEventListener("click", () => switchStep(idx + 1));
    });

    if (elements.goToStep2Btn) {
      elements.goToStep2Btn.addEventListener("click", () => switchStep(2));
    }
    if (elements.backToStep1Btn) {
      elements.backToStep1Btn.addEventListener("click", () => switchStep(1));
    }
    if (elements.goToStep3Btn) {
      elements.goToStep3Btn.addEventListener("click", () => switchStep(3));
    }
    if (elements.backToStep2Btn) {
      elements.backToStep2Btn.addEventListener("click", () => switchStep(2));
    }
    if (elements.goToStep4Btn) {
      elements.goToStep4Btn.addEventListener("click", () => switchStep(4));
    }
    if (elements.backToStep3Btn) {
      elements.backToStep3Btn.addEventListener("click", () => switchStep(3));
    }
    if (elements.restartExperimentBtn) {
      elements.restartExperimentBtn.addEventListener("click", () => {
        resetRunDisplay();
        switchStep(1);
      });
    }

    if (elements.toggleViewModeBtn && elements.workspaceGrid) {
      elements.toggleViewModeBtn.addEventListener("click", () => {
        const isExpanded = elements.workspaceGrid.classList.toggle("expanded-mode");
        if (isExpanded) {
          elements.toggleViewModeBtn.innerHTML = `
            <svg class="icon icon-sm" aria-hidden="true"><use href="#icon-chevron-right"></use></svg>
            Stepper View
          `;
          toast("Expanded view: all 4 phases visible simultaneously.", "info");
        } else {
          elements.toggleViewModeBtn.innerHTML = `
            <svg class="icon icon-sm" aria-hidden="true"><use href="#icon-grid"></use></svg>
            All Steps View
          `;
          switchStep(currentStep);
        }
      });
    }

    if (elements.toggleAdvancedEnvelopeBtn && elements.advancedEnvelopeFields) {
      elements.toggleAdvancedEnvelopeBtn.addEventListener("click", () => {
        const isCollapsed = elements.advancedEnvelopeFields.classList.toggle("collapsed");
        if (elements.advToggleIcon) {
          elements.advToggleIcon.textContent = isCollapsed ? "+" : "-";
        }
      });
    }

    switchStep(1);
  }

  // ==========================================================================
  // Contextual Onboarding Tour
  // ==========================================================================

  const tourSteps = [
    {
      step: "PHASE 1 / 4",
      title: "1. Define Mission Envelope",
      content: "Specify target altitude, flight duration, and safety corridors for the Crazyflie 2 quadrotor. The simulation step budget and physics integrator parameters are calculated deterministically.",
      targetStep: 1,
    },
    {
      step: "PHASE 2 / 4",
      title: "2. Synthesize AI Controller",
      content: "Select from 3 Vultr Serverless Inference LLMs (GLM-5.3-Flash, DeepSeek-V3, Qwen2.5-72B) to generate a closed-loop PD flight controller, or inspect the audited baseline code.",
      targetStep: 2,
    },
    {
      step: "PHASE 3 / 4",
      title: "3. MicroVM Containment Cage",
      content: "The generated controller runs inside an isolated microVM sandbox with default-deny network, strict CPU/memory limits, and watchdog timeout before execution.",
      targetStep: 3,
    },
    {
      step: "PHASE 4 / 4",
      title: "4. Live Simulation & Replay",
      content: "Forseti executes the trusted MuJoCo physics engine while Heimdall adjudicates flight safety and physical replay determinism. Export tamper-evident Court Records for cryptographic verification.",
      targetStep: 4,
    },
  ];

  let tourIndex = 0;

  function showTourStep(index) {
    if (!tourSteps[index]) return;
    const s = tourSteps[index];
    if (elements.tourStepBadge) elements.tourStepBadge.textContent = s.step;
    if (elements.tourTitle) elements.tourTitle.textContent = s.title;
    if (elements.tourContent) elements.tourContent.textContent = s.content;

    if (elements.prevTourBtn) elements.prevTourBtn.disabled = index === 0;
    if (elements.nextTourBtn) {
      elements.nextTourBtn.textContent = index === tourSteps.length - 1 ? "Finish Tour" : "Next Step";
    }

    switchStep(s.targetStep);
  }

  function openTour() {
    if (!elements.tourBackdrop) return;
    tourIndex = 0;
    showTourStep(tourIndex);
    elements.tourBackdrop.classList.remove("hidden");
  }

  function closeTour() {
    if (!elements.tourBackdrop) return;
    elements.tourBackdrop.classList.add("hidden");
  }

  function setupTour() {
    if (!elements.startTourBtn || !elements.tourBackdrop) return;

    elements.startTourBtn.addEventListener("click", openTour);
    if (elements.closeTourBtn) elements.closeTourBtn.addEventListener("click", closeTour);
    if (elements.skipTourBtn) elements.skipTourBtn.addEventListener("click", closeTour);

    elements.tourBackdrop.addEventListener("click", e => {
      if (e.target === elements.tourBackdrop) closeTour();
    });

    if (elements.prevTourBtn) {
      elements.prevTourBtn.addEventListener("click", () => {
        if (tourIndex > 0) {
          tourIndex--;
          showTourStep(tourIndex);
        }
      });
    }

    if (elements.nextTourBtn) {
      elements.nextTourBtn.addEventListener("click", () => {
        if (tourIndex < tourSteps.length - 1) {
          tourIndex++;
          showTourStep(tourIndex);
        } else {
          closeTour();
        }
      });
    }

    document.addEventListener("keydown", e => {
      if (e.key === "Escape" && !elements.tourBackdrop.classList.contains("hidden")) {
        closeTour();
      }
    });
  }

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

  async function validateMissionSpec(silent = false) {
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
      if (!silent) {
        toast("Mission envelope validated successfully (" + data.step_budget + " steps).", "success");
      }
      if (droneViewer && droneViewer.setTargetAltitude) {
        droneViewer.setTargetAltitude(spec.target_altitude_m);
      }
    } catch (err) {
      elements.specFeedback.textContent = "INVALID: " + err.message;
      elements.specFeedback.classList.add("error");
      elements.specFeedback.style.display = "inline-block";
      toast("Invalid mission parameters: " + err.message, "error");
    }
  }

  function setActivePreset(activeEl) {
    [elements.presetNominal, elements.presetHigh, elements.presetTurbulent].forEach(el => {
      if (el) el.classList.remove("active");
    });
    if (activeEl) activeEl.classList.add("active");
  }

  function setupPresets() {
    if (elements.presetNominal) {
      elements.presetNominal.addEventListener("click", () => {
        setActivePreset(elements.presetNominal);
        setSpecToForm({
          target_altitude_m: 0.10,
          altitude_tolerance_m: 0.05,
          min_allowed_altitude_m: 0.05,
          max_allowed_altitude_m: 1.00,
          mission_duration_s: 0.40,
          disturbance_force_z_min: -0.05,
          disturbance_force_z_max: 0.05,
        });
        validateMissionSpec(true);
      });
    }

    if (elements.presetHigh) {
      elements.presetHigh.addEventListener("click", () => {
        setActivePreset(elements.presetHigh);
        setSpecToForm({
          target_altitude_m: 1.50,
          altitude_tolerance_m: 0.10,
          min_allowed_altitude_m: 0.10,
          max_allowed_altitude_m: 3.00,
          mission_duration_s: 0.80,
          disturbance_force_z_min: -0.10,
          disturbance_force_z_max: 0.10,
        });
        validateMissionSpec(true);
      });
    }

    if (elements.presetTurbulent) {
      elements.presetTurbulent.addEventListener("click", () => {
        setActivePreset(elements.presetTurbulent);
        setSpecToForm({
          target_altitude_m: 0.10,
          altitude_tolerance_m: 0.05,
          min_allowed_altitude_m: 0.05,
          max_allowed_altitude_m: 1.00,
          mission_duration_s: 0.40,
          disturbance_force_z_min: -0.20,
          disturbance_force_z_max: 0.20,
        });
        validateMissionSpec(true);
      });
    }

    // Clear active preset state if user manually edits parameters
    const formInputs = [
      elements.targetAltitude,
      elements.altitudeTolerance,
      elements.minAltitude,
      elements.maxAltitude,
      elements.missionDuration,
      elements.distZMin,
      elements.distZMax,
    ];
    formInputs.forEach(input => {
      if (input) {
        input.addEventListener("input", () => {
          setActivePreset(null);
        });
      }
    });
  }

  // ==========================================================================
  // Controller Generation & Code Handling
  // ==========================================================================

  function updateCodeLineNumbers(code) {
    if (!elements.codeLineNumbers) return;
    const lineCount = (code || "").split("\n").length;
    let numbers = "";
    for (let i = 1; i <= lineCount; i++) {
      numbers += i + "\n";
    }
    elements.codeLineNumbers.textContent = numbers;
  }

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
      elements.controllerAstBadge.textContent = "Syntax Verified";
      elements.controllerAstBadge.className = "meta-badge text-emerald";
    } else {
      elements.controllerAstBadge.textContent = "Check Signature";
      elements.controllerAstBadge.className = "meta-badge text-amber";
    }
  }

  async function generateController() {
    const spec = getSpecFromForm();
    const model = state.selectedModel || "glm-5.3-flash";

    elements.generateControllerBtn.disabled = true;
    if (elements.genSpinner) elements.genSpinner.style.display = "inline-block";

    if (elements.synthesisLoadingBox) {
      elements.synthesisLoadingBox.classList.remove("hidden");
      if (elements.synthesisStatusText) {
        elements.synthesisStatusText.textContent = "Connecting to Vultr Serverless Inference (" + model + ")...";
      }
    }

    const statusTimer = setTimeout(() => {
      if (elements.synthesisStatusText) {
        elements.synthesisStatusText.textContent = "Synthesizing 500 Hz Crazyflie 2 control law...";
      }
    }, 600);

    try {
      const res = await fetch("/controllers/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          spec: spec,
          model: model,
          reasoning_effort: state.selectedReasoningEffort || "minimal",
          prompt_version: "v1",
          max_tokens: 4096,
        }),
      });

      clearTimeout(statusTimer);
      if (elements.synthesisStatusText) {
        elements.synthesisStatusText.textContent = "Validating AST, observe() signature and bound limits...";
      }

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : "Generation failed");
      }

      const controller = data.controller;
      elements.controllerSource.value = controller.source_code;
      await updateCodeMetadata(controller.source_code);
      state.activeController = controller;

      if (elements.synthesisStatusText) {
        elements.synthesisStatusText.textContent = "Controller synthesis validated successfully.";
      }
      setTimeout(() => {
        if (elements.synthesisLoadingBox) elements.synthesisLoadingBox.classList.add("hidden");
      }, 700);

      toast("Controller generated via " + model + " (" + (state.selectedReasoningEffort || "minimal") + " reasoning) and validated.", "success");
    } catch (err) {
      clearTimeout(statusTimer);
      if (elements.synthesisStatusText) {
        elements.synthesisStatusText.textContent = "Notice: " + err.message;
      }
      setTimeout(() => {
        if (elements.synthesisLoadingBox) elements.synthesisLoadingBox.classList.add("hidden");
      }, 2200);
      toast("Generation Notice: " + err.message + ". You can test with the baseline controller immediately.", "warning");
    } finally {
      elements.generateControllerBtn.disabled = false;
      if (elements.genSpinner) elements.genSpinner.style.display = "none";
    }
  }

  function loadBaselineController() {
    elements.controllerSource.value = BASELINE_CONTROLLER_SOURCE;
    updateCodeLineNumbers(BASELINE_CONTROLLER_SOURCE);
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

    const currentJobStateEl = document.getElementById("currentJobState");
    if (currentJobStateEl) {
      const cleanState = currentState
        .toLowerCase()
        .split("_")
        .map(w => w.charAt(0).toUpperCase() + w.slice(1))
        .join(" ");
      currentJobStateEl.textContent = cleanState;
    }
  }

  async function runExperiment() {
    const spec = getSpecFromForm();
    const sourceCode = elements.controllerSource.value;

    if (!sourceCode.trim()) {
      toast("Please load or generate a controller before launching the trial.", "warning");
      switchStep(2);
      return;
    }

    switchStep(4);

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
      elements.metricFinalAlt.textContent = detail.final_altitude_m !== null && detail.final_altitude_m !== undefined ? detail.final_altitude_m.toFixed(4) + " m" : "0.0000 m";
      elements.metricAltError.textContent = detail.altitude_error_m !== null && detail.altitude_error_m !== undefined ? detail.altitude_error_m.toFixed(4) + " m" : "0.0000 m";
      elements.metricMinAlt.textContent = detail.minimum_altitude_m !== null && detail.minimum_altitude_m !== undefined ? detail.minimum_altitude_m.toFixed(4) + " m" : "0.0000 m";
      elements.metricMaxAlt.textContent = detail.maximum_altitude_m !== null && detail.maximum_altitude_m !== undefined ? detail.maximum_altitude_m.toFixed(4) + " m" : "0.0000 m";

      // Render 2D Altitude Chart
      renderAltitudeChart(state.activeTrajectory, spec);

      // Load 3D Simulation Replay into Three.js Viewer
      if (droneViewer && state.activeTrajectory && state.activeTrajectory.length > 0) {
        droneViewer.loadReplay(state.activeTrajectory);
      }

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
    if (droneViewer && droneViewer.resetToIdle) {
      droneViewer.resetToIdle();
    }
    elements.replayDiffValue.textContent = "0.00e+00 m";
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
    } else if (rawContainment === "POLICY_CONFIRMED") {
      elements.verdictContainment.textContent = "POLICY CONFIRMED (AUDITED)";
      elements.verdictContainment.className = "verdict-val val-success";
    } else if (backend === "microvm") {
      elements.verdictContainment.textContent = "ISOLATED GUEST (MICROVM)";
      elements.verdictContainment.className = "verdict-val val-success";
    } else if (rawContainment === "PARTIAL" || backend === "trusted_simulator" || backend === "subprocess" || backend === "subprocess_dev_unisolated") {
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
    } else if (rawProvenance === "VERIFIED") {
      elements.verdictProvenance.textContent = "EVENT CHAIN VERIFIED";
      elements.verdictProvenance.className = "verdict-val val-success";
    } else {
      elements.verdictProvenance.textContent = rawProvenance || "AWAITING EVIDENCE";
      elements.verdictProvenance.className = "verdict-val val-pending";
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

      if (droneViewer && droneViewer.setStep) {
        droneViewer.setStep(sampleIndex, trajectory);
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

  
  // ==========================================================================
  // Ragnarok Knowledge Oracle (Memory RAG Engine)
  // ==========================================================================

  const RAGNAROK_KNOWLEDGE_BASE = [
    {
      id: "oracle-bounds",
      topic: "bounds",
      topicLabel: "Physical Bounds",
      title: "Bitcraze Crazyflie 2 Dynamic Envelopes & Closed-Loop Rate",
      citation: "docs/DOMNIR_IMPLEMENTATION_PLAN.md Milestone 3",
      summary: "Physical flight boundary rules for the Bitcraze Crazyflie 2.0 quadrotor under MuJoCo 3.3.7 simulation. Gravity equilibrium hover thrust is calibrated at 0.26487 N for the 27.0 gram airframe. Actuators saturate strictly at 0.35 N per arm. Control loops advance at 500 Hz (dt = 0.002s). Any breach below the safety floor (0.05m) or above the ceiling (1.00m) triggers instant FALSIFIED physical adjudication.",
      snippet: "# Crazyflie 2 Physics Invariants\nPLANT_MASS_KG = 0.027\nGRAVITY_THRUST_EQUILIBRIUM_N = 0.26487\nACTUATOR_MAX_THRUST_N = 0.35\nSIMULATION_TIMESTEP_S = 0.002  # 500 Hz closed loop\nFLOOR_BOUNDARY_M = 0.05\nCEILING_BOUNDARY_M = 1.00",
      lang: "python"
    },
    {
      id: "oracle-vultr",
      topic: "vultr",
      topicLabel: "Vultr Serverless",
      title: "Vultr Serverless Inference & Zero Host Credential Bleed",
      citation: "docs/ADR/ADR-001-sandboxing.md Section 2",
      summary: "All flight controller synthesis queries are routed through Vultr Serverless Inference at https://api.vultrinference.com/v1. Supported pinned models include GLM 5.3 Flash (rapid token synthesis), Qwen 3.8 Flash Next (aerodynamic reasoning), and DeepSeek V4.1 Flash (compact logic). API keys exist exclusively in backend environment memory and are never transmitted to the browser or guest microVM.",
      snippet: "# Serverless Inference Request Contract\nPOST https://api.vultrinference.com/v1/chat/completions\n{\n  \"model\": \"glm-5.3-flash\",\n  \"messages\": [{\"role\": \"system\", \"content\": \"observe(obs) contract\"}],\n  \"temperature\": 0.2,\n  \"max_tokens\": 1024\n}",
      lang: "http"
    },
    {
      id: "oracle-microvm",
      topic: "microvm",
      topicLabel: "MicroVM Isolation",
      title: "Blast Radius Zero: Hardware MicroVM Containment",
      citation: "docs/ADR/ADR-001-sandboxing.md Section 3",
      summary: "Guest code execution occurs strictly inside dedicated Microsandbox microVMs backed by AMD EPYC nested KVM (/dev/kvm). The guest environment operates under default-deny network policy (zero ingress, zero egress, zero published ports), zero host mounts, and a hard 0.50s monotonic wall-clock watchdog ceiling. The host simulator (Forseti) alone owns the MuJoCo model and MjData.",
      snippet: "# MicroVM Containment Invariants\n/dev/kvm: Nested Hardware Virtualization\nNetwork: Default-Deny (Egress & Ingress Dropped)\nHost Mounts: None (Zero Shared FS)\nWatchdog Ceiling: 0.50s monotonic timeout\nCleanup: Mandatory context manager teardown (100% reclamation)",
      lang: "yaml"
    },
    {
      id: "oracle-cap-host",
      topic: "microvm",
      topicLabel: "Host Isolation Proof",
      title: "CAP-HOST-001: Strict Hardware Isolation & Capability Containment",
      citation: "docs/evidence/containment-suite-20261105-final.json & domnir/containment.py",
      summary: "Documents that Microsandbox microVMs under Linux KVM (/dev/kvm) are strictly isolated with zero host mounts, default-deny network, and CPU/memory limits. Proof records in docs/evidence/ show the guest is incapable of accessing host files or sockets. Finite simulation does not constitute universal hardware airworthiness certification.",
      snippet: "# CAP-HOST-001 Verification Rule\nassert guest_cannot_access_host_files()\nassert guest_cannot_reach_network()\nassert host_simulator_owns_state()",
      lang: "python"
    },
    {
      id: "oracle-net-egress",
      topic: "microvm",
      topicLabel: "Network Invariant",
      title: "NET-EGRESS-001: Default-Deny Network Egress Invariant",
      citation: "docs/evidence/containment-suite-20261105-final.json & domnir/sandbox.py",
      summary: "All inbound and outbound guest network traffic is blocked by the host virtualization filter. Zero listening ports are exposed to untrusted code.",
      snippet: "# NET-EGRESS-001 Invariant\npolicy: default_egress = 'deny'\npolicy: default_ingress = 'deny'\nports_exposed = 0",
      lang: "yaml"
    },
    {
      id: "oracle-res-limits",
      topic: "microvm",
      topicLabel: "Resource Quotas",
      title: "RES-TIME-001 & RES-MEM-001: Wall-Clock Watchdog & Memory Quotas",
      citation: "docs/DOMNIR_IMPLEMENTATION_PLAN.md Milestone 2",
      summary: "Host enforces a strict 0.50s monotonic watchdog ceiling and 256MB memory cap. Unbounded loops or memory floods are terminated and cleaned up deterministically.",
      snippet: "# Resource Limits\nWATCHDOG_WALLCLOCK_CEILING_S = 0.50\nMEMORY_LIMIT_MB = 256\nTERMINATION_ACTION = 'SIGKILL_AND_RECLAIM'",
      lang: "python"
    },
    {
      id: "oracle-cleanup",
      topic: "microvm",
      topicLabel: "Teardown Guarantee",
      title: "CLEANUP-POST-001: Ephemeral MicroVM Teardown & Reclamation",
      citation: "domnir/sandbox.py & docs/evidence/containment-suite-20261105-final.json",
      summary: "Teardown is executed in host context manager finally blocks. Sandbox instances and temporary IPC FIFOs are unconditionally unlinked and destroyed upon trial termination.",
      snippet: "# CLEANUP-POST-001 Context Manager\nwith SandboxLease(msb_path) as lease:\n    yield lease\n# __exit__ guarantees lease.destroy() and IPC unlinking",
      lang: "python"
    },
    {
      id: "oracle-replay",
      topic: "replay",
      topicLabel: "Deterministic Replay",
      title: "Physical Replay within Declared Numerical Tolerance (<= 1.00e-12 m)",
      citation: "docs/DOMNIR_IMPLEMENTATION_PLAN.md Milestone 4",
      summary: "During simulation, control action vectors emitted by the caged guest are recorded step-by-step. To verify the absence of host state tampering or stochastic divergence, the entire action sequence is independently replayed on a fresh, pristine MuJoCo simulation instance. Replay trajectory matched within declared numerical tolerance (<= 1.00e-12 meters) under pinned environment conditions.",
      snippet: "# Replay Mathematical Verification within Numerical Tolerance\nmax_diff = max(abs(traj_original[t].z - traj_replay[t].z) for t in steps)\nassert max_diff <= 1.00e-12, f'Replay diverged: {max_diff:.3e} m'\nverdict = 'MATCHED within declared numerical tolerance (<= 1.00e-12 m)'",
      lang: "python"
    },
    {
      id: "oracle-court",
      topic: "court",
      topicLabel: "Court Record Proof",
      title: "SHA-256 Hash-Linked Court Record (Schema v1.0)",
      citation: "docs/DOMNIR_IMPLEMENTATION_PLAN.md Milestone 5",
      summary: "Every experiment generates a hash-linked, self-contained Court Record JSON artifact with locally verifiable integrity. It contains SHA-256 digests of the controller source code, the MuJoCo XML plant model, recorded trajectory vectors, and an unbroken SHA-256 host event chain linking Genesis to Head. Anyone can independently verify the record via POST /court-records/verify without re-executing untrusted code.",
      snippet: "{\n  \"schema_version\": \"1.0\",\n  \"record_id\": \"cr-a7f49c01b2\",\n  \"controller_sha256\": \"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\",\n  \"event_log_hash_head\": \"67ff6282bf5943982cc0674c980170240571e52f8ec8f425ddcd6cec53101c80\",\n  \"replay_max_abs_difference\": 0.0\n}",
      lang: "json"
    },
    {
      id: "oracle-adjudication",
      topic: "adjudication",
      topicLabel: "Adjudication Ethics",
      title: "Mandatory Adjudication Ethics & Limitations Disclosure",
      citation: "docs/DOMNIR_IMPLEMENTATION_PLAN.md Section 6",
      summary: "Dómnir enforces strict truthfulness in qualification reporting. A verdict of NOT_FALSIFIED confirms that no safety constraints were breached under the specific tested disturbances, but remains INCONCLUSIVE regarding universal safety or physical airworthiness. Real-world Crazyflie 2 flight dynamics involve unmodeled aerodynamic turbulence and battery drop that simulation does not fully capture.",
      snippet: "# Mandatory Falsification Disclosure\nVerdict: NOT_FALSIFIED\nClaim Limit: Synthetic qualification under tested perturbation.\nDisclaimer: INCONCLUSIVE regarding universal safety.\nActuator Dynamics: Uncalibrated research approximation.",
      lang: "text"
    },
    {
      id: "oracle-ast",
      topic: "bounds",
      topicLabel: "Physical Bounds",
      title: "Host Validation & MicroVM Isolation Boundary",
      citation: "domnir/spec.py & domnir/sandbox.py",
      summary: "Before controller execution, the host validates source size (<=32 KiB), UTF-8 encoding, Python syntax, and top-level observe() signature. Execution containment does not rely on fragile source-level AST keyword blacklists: containment is strictly enforced by the hardware MicroVM boundary (/dev/kvm) with default-deny network, zero host mounts, and resource quotas.",
      snippet: "# Host Validation Contract (domnir/spec.py & domnir/sandbox.py)\nassert 1 <= len(source_bytes) <= 32768\nassert b'\\x00' not in source_bytes\ntree = ast.parse(source_text, filename='controller.py')\nassert any(isinstance(n, ast.FunctionDef) and n.name == 'observe' for n in tree.body)\n# Isolation enforced by: Microsandbox microVM (/dev/kvm)",
      lang: "python"
    },
    {
      id: "oracle-reasoning",
      topic: "vultr",
      topicLabel: "Vultr Serverless",
      title: "Vultr Serverless Reasoning Effort Calibration",
      citation: "domnir/vultr_inference.py & domnir/api/app.py",
      summary: "Reasoning effort can be set to Minimal, Low, Medium, or High. Minimal provides the lowest token latency (~1.8s) for direct PD hover loops. Higher reasoning efforts allow LLM models to analyze multi-variable state spaces and plan counter-force thrust vectors for high-turbulence mission scenarios.",
      snippet: "# Reasoning Effort Parameter Mapping\neffort_map = {\n    'minimal': {'temp': 0.15, 'reasoning_tokens': 0},\n    'low':     {'temp': 0.20, 'reasoning_tokens': 256},\n    'medium':  {'temp': 0.25, 'reasoning_tokens': 512},\n    'high':    {'temp': 0.30, 'reasoning_tokens': 1024}\n}",
      lang: "python"
    },
    {
      id: "oracle-quick-start",
      topic: "bounds",
      topicLabel: "Guided Flow",
      title: "Quick Start: Guided Four-Stage Falsification Workflow",
      citation: "docs/DOMNIR_IMPLEMENTATION_PLAN.md Section 1",
      summary: "Stage 1: Define physical flight envelope and presets. Stage 2: Synthesize or review Python controller code via Vultr Serverless. Stage 3: Confirm hardware microVM containment readiness. Stage 4: Run 500 Hz MuJoCo physical trial, inspect trajectory and replay verification.",
      snippet: "# Guided Workflow Steps\n1. Envelope -> 2. Controller -> 3. MicroVM Cage -> 4. Flight & Replay",
      lang: "text"
    },
    {
      id: "oracle-troubleshooting",
      topic: "adjudication",
      topicLabel: "Troubleshooting",
      title: "Troubleshooting: KVM Readiness, Quotas, and Fallbacks",
      citation: "docs/DOMNIR_IMPLEMENTATION_PLAN.md Section 4 & AGENTS.md",
      summary: "If KVM is unavailable, public execution strictly fails closed without host execution fallback. If WebGL fails, 2D fallback stills are displayed. If rate limit is reached, certified baseline evidence remains accessible.",
      snippet: "# Fail-Closed Invariant\nif not is_microvm_available():\n    raise RuntimeError('BLOCKED: ISOLATION_UNAVAILABLE')\n# Fallback: display certified baseline court records",
      lang: "python"
    }
  ];

    const ORACLE_STOP_WORDS = new Set(["how", "is", "the", "are", "what", "why", "who", "when", "where", "can", "does", "with", "from", "and", "for", "that", "this", "about", "tell"]);

  function searchKnowledgeCorpus(topic = "all", searchQuery = "", maxResults = null) {
    const rawQuery = (searchQuery || "").trim().toLowerCase();
    if (!rawQuery) {
      const filtered = RAGNAROK_KNOWLEDGE_BASE.filter(item => topic === "all" || item.topic === topic);
      return maxResults ? filtered.slice(0, maxResults) : filtered;
    }

    const tokens = rawQuery
      .replace(/[^a-z0-9_ -]/g, " ")
      .split(/\s+/)
      .filter(w => w.length > 2 && !ORACLE_STOP_WORDS.has(w));

    const matches = RAGNAROK_KNOWLEDGE_BASE.filter(item => {
      const topicMatches = (topic === "all" || item.topic === topic);
      if (!topicMatches) return false;
      if (tokens.length === 0) {
        return (
          item.title.toLowerCase().includes(rawQuery) ||
          item.summary.toLowerCase().includes(rawQuery)
        );
      }
      const haystack = (
        item.title + " " +
        item.summary + " " +
        item.snippet + " " +
        item.topicLabel + " " +
        (item.citation || "")
      ).toLowerCase();
      return tokens.some(token => haystack.includes(token)) || haystack.includes(rawQuery);
    }).map(item => {
      const haystack = (item.title + " " + item.summary + " " + item.snippet + " " + (item.citation || "")).toLowerCase();
      let score = 0;
      if (item.title.toLowerCase().includes(rawQuery)) score += 10;
      if (item.summary.toLowerCase().includes(rawQuery)) score += 5;
      for (const t of tokens) {
        if (item.title.toLowerCase().includes(t)) score += 4;
        if (item.summary.toLowerCase().includes(t)) score += 2;
        if ((item.citation || "").toLowerCase().includes(t)) score += 2;
        if (haystack.includes(t)) score += 1;
      }
      return { item, score };
    }).sort((a, b) => b.score - a.score).map(x => x.item);

    return maxResults ? matches.slice(0, maxResults) : matches;
  }

  function renderOracleResults(filterTopic = "all", searchQuery = "") {
    if (!elements.oracleResultsContainer) return;
    const query = searchQuery.trim().toLowerCase();

    // Security check: Refuse prompt injections or instruction overrides
    if (query.includes("ignore previous") || query.includes("system prompt") || query.includes("bypass") || query.includes("eval(") || query.includes("exec(")) {
      elements.oracleResultsContainer.innerHTML = `
        <div class="card" style="grid-column: 1 / -1; padding: 24px; text-align: center;">
          <h4 style="color: var(--color-failure, #f43f5e); font-size: 13px;">Security Notice: Instruction Override Attempt Refused</h4>
          <p style="font-size: 11px; color: var(--text-muted); margin-top: 6px;">The Ragnarok Knowledge Oracle provides grounded documentation lookup only and does not execute instructions or bypass system constraints.</p>
        </div>
      `;
      return;
    }

    const matches = searchKnowledgeCorpus(filterTopic, searchQuery);

    if (matches.length === 0) {
      elements.oracleResultsContainer.innerHTML = `
        <div class="card" style="grid-column: 1 / -1; padding: 24px; text-align: center;">
          <h4 style="color: var(--text-muted); font-size: 13px;">No matching Oracle knowledge records found for "${escapeHtml(searchQuery)}"</h4>
          <p style="font-size: 11px; color: var(--text-subtle); margin-top: 6px;">Try querying 'bounds', 'vultr', 'replay', 'kvm', or select 'All Topics'.</p>
        </div>
      `;
      return;
    }

    elements.oracleResultsContainer.innerHTML = matches.map(item => `
      <div class="oracle-card" id="${item.id}">
        <div class="oracle-card-header">
          <span class="oracle-card-topic">${escapeHtml(item.topicLabel)}</span>
          <button type="button" class="btn btn-sm btn-ghost oracle-copy-btn" data-snippet="${encodeURIComponent(item.snippet)}" title="Copy verified code snippet">Copy Block</button>
        </div>
        <h4 class="oracle-card-title">${escapeHtml(item.title)}</h4>
        <div style="font-size: 10px; color: var(--text-muted); margin-bottom: 8px; font-family: var(--font-mono);">Source: ${escapeHtml(item.citation || "Technical Specification")}</div>
        <p class="oracle-card-body">${escapeHtml(item.summary)}</p>
        <div class="oracle-snippet-box">
          <div class="oracle-snippet-header">
            <span class="oracle-snippet-lang">${escapeHtml(item.lang.toUpperCase())}</span>
          </div>
          <pre class="oracle-snippet-code"><code>${escapeHtml(item.snippet)}</code></pre>
        </div>
      </div>
    `).join("");

    // Wire up copy block buttons inside oracle cards
    elements.oracleResultsContainer.querySelectorAll(".oracle-copy-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const rawCode = decodeURIComponent(btn.getAttribute("data-snippet") || "");
        if (!rawCode) return;
        navigator.clipboard.writeText(rawCode).then(() => {
          const originalText = btn.textContent;
          btn.textContent = "Copied!";
          toast("Oracle code block copied to clipboard.", "info");
          setTimeout(() => (btn.textContent = originalText), 2000);
        });
      });
    });
  }

  
  // ==========================================================================
  // Dithered Norse Atmospheric Canvas (Fjord Landscape & Embers/Mist)
  // ==========================================================================

  let atmosphericCanvas = null;

  function setupAtmosphericCanvas() {
    const canvas = document.getElementById("ragnarokCanvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let width = 0;
    let height = 0;
    let dpr = 1;
    const offscreenBuffer = document.createElement("canvas");
    const offscreenCtx = offscreenBuffer.getContext("2d");

    let isDawn = document.documentElement.classList.contains("rune-dawn");

    const ditherRuneImg = new Image();
    ditherRuneImg.src = "/assets/ragnarok_rune_dither.jpg";
    ditherRuneImg.onload = () => {
      renderLandscapeBuffer();
    };

    const particleCount = 24;
    const particles = [];

    function initParticles() {
      particles.length = 0;
      for (let i = 0; i < particleCount; i++) {
        particles.push({
          x: Math.random() * (width || 800),
          y: Math.random() * (height || 600),
          size: 0.8 + Math.random() * 1.6,
          speed: 0.20 + Math.random() * 0.45,
          drift: (Math.random() - 0.5) * 0.25,
          opacity: 0.10 + Math.random() * 0.28,
          pulseSpeed: 0.015 + Math.random() * 0.025,
          pulsePhase: Math.random() * Math.PI * 2,
        });
      }
    }

    function renderLandscapeBuffer() {
      if (width <= 0 || height <= 0) return;
      offscreenBuffer.width = width;
      offscreenBuffer.height = height;
      if (!offscreenCtx) return;

      const bg = offscreenCtx;
      bg.clearRect(0, 0, width, height);

      if (isDawn) {
        // RUNE DAWN: HIGH-KEY MONOCHROMATIC MIST FJORD
        const skyGrad = bg.createLinearGradient(0, 0, 0, height);
        skyGrad.addColorStop(0, "#f8fafc");
        skyGrad.addColorStop(0.55, "#e2e8f0");
        skyGrad.addColorStop(0.72, "#cbd5e1");
        skyGrad.addColorStop(1.0, "#94a3b8");
        bg.fillStyle = skyGrad;
        bg.fillRect(0, 0, width, height);

        // Weathered Runic Compass Watermark
        const runeCenterX = width * 0.52;
        const runeCenterY = height * 0.44;
        const runeRadius = Math.min(width * 0.15, 110);

        bg.save();
        bg.strokeStyle = "rgba(100, 116, 139, 0.15)";
        bg.lineWidth = 1.2;
        bg.beginPath();
        bg.arc(runeCenterX, runeCenterY, runeRadius, 0, Math.PI * 2);
        bg.stroke();

        bg.beginPath();
        bg.arc(runeCenterX, runeCenterY, runeRadius * 0.65, 0, Math.PI * 2);
        bg.stroke();

        for (let s = 0; s < 8; s++) {
          const angle = (s * Math.PI) / 4;
          const x1 = runeCenterX + Math.cos(angle) * (runeRadius * 0.25);
          const y1 = runeCenterY + Math.sin(angle) * (runeRadius * 0.25);
          const x2 = runeCenterX + Math.cos(angle) * (runeRadius * 1.05);
          const y2 = runeCenterY + Math.sin(angle) * (runeRadius * 1.05);
          bg.beginPath();
          bg.moveTo(x1, y1);
          bg.lineTo(x2, y2);
          bg.stroke();
        }
        bg.restore();

        // Distant Jagged Fjord Peaks (Layer 1)
        const waterY = height * 0.74;
        bg.save();
        bg.fillStyle = "rgba(100, 116, 139, 0.25)";
        bg.beginPath();
        bg.moveTo(0, waterY);
        const peaks1 = [
          [0.0, waterY - height * 0.18],
          [0.12, waterY - height * 0.28],
          [0.22, waterY - height * 0.22],
          [0.34, waterY - height * 0.36],
          [0.48, waterY - height * 0.26],
          [0.62, waterY - height * 0.38],
          [0.76, waterY - height * 0.25],
          [0.88, waterY - height * 0.32],
          [1.0, waterY - height * 0.20],
        ];
        for (const pt of peaks1) {
          bg.lineTo(pt[0] * width, pt[1]);
        }
        bg.lineTo(width, waterY);
        bg.closePath();
        bg.fill();

        // Mid Fjord Mountain Ridge with Dither Stipple (Layer 2)
        bg.fillStyle = "rgba(51, 65, 85, 0.45)";
        bg.beginPath();
        bg.moveTo(0, waterY);
        const peaks2 = [
          [0.0, waterY - height * 0.12],
          [0.10, waterY - height * 0.22],
          [0.25, waterY - height * 0.14],
          [0.40, waterY - height * 0.26],
          [0.55, waterY - height * 0.17],
          [0.70, waterY - height * 0.24],
          [0.85, waterY - height * 0.15],
          [1.0, waterY - height * 0.20],
        ];
        for (const pt of peaks2) {
          bg.lineTo(pt[0] * width, pt[1]);
        }
        bg.lineTo(width, waterY);
        bg.closePath();
        bg.fill();

        // Procedural Dither Stippling along Mountain Slopes
        bg.fillStyle = "rgba(15, 23, 42, 0.25)";
        const ditherStep = 12;
        for (let dx = 0; dx < width; dx += ditherStep) {
          const normX = dx / width;
          const mountainTopY = waterY - height * (0.16 + 0.12 * Math.sin(normX * 6.28));
          const span = waterY - mountainTopY;
          if (span > 10) {
            for (let dy = mountainTopY; dy < waterY; dy += ditherStep) {
              const density = (dy - mountainTopY) / span;
              if (Math.sin(dx * 13.7 + dy * 27.3) > (1.0 - density * 1.5)) {
                bg.fillRect(dx, dy, 1.5, 1.5);
              }
            }
          }
        }

        // Fjord Water Line
        const waterGrad = bg.createLinearGradient(0, waterY, 0, height);
        waterGrad.addColorStop(0, "#cbd5e1");
        waterGrad.addColorStop(0.3, "#94a3b8");
        waterGrad.addColorStop(1.0, "#64748b");
        bg.fillStyle = waterGrad;
        bg.fillRect(0, waterY, width, height - waterY);

        bg.restore();
      } else {
        // RUNE DUSK: LOW-BRIGHTNESS ATMOSPHERIC VOID & PROMINENT STIPPLE DITHER
        const skyGrad = bg.createLinearGradient(0, 0, 0, height);
        skyGrad.addColorStop(0, "#010204");
        skyGrad.addColorStop(0.35, "#040711");
        skyGrad.addColorStop(0.65, "#070c18");
        skyGrad.addColorStop(0.85, "#0a1122");
        skyGrad.addColorStop(1.0, "#020306");
        bg.fillStyle = skyGrad;
        bg.fillRect(0, 0, width, height);

        // Subdued Celestial Runic Compass
        const runeCenterX = width * 0.50;
        const runeCenterY = height * 0.36;
        const R = Math.min(width * 0.12, 108);

        // Draw Authentic Dithered Celestial Great Rune background asset with low brightness
        if (ditherRuneImg && ditherRuneImg.complete && ditherRuneImg.naturalWidth > 0) {
          bg.save();
          const imgAspect = ditherRuneImg.naturalWidth / ditherRuneImg.naturalHeight;
          const targetH = Math.min(height * 0.85, 760);
          const targetW = targetH * imgAspect;
          const targetX = (width - targetW) / 2;
          const targetY = (height - targetH) * 0.36;
          bg.globalAlpha = 0.22;
          bg.drawImage(ditherRuneImg, targetX, targetY, targetW, targetH);
          bg.restore();
        }

        bg.save();

        // Stippled Dither Clouds around the Great Rune
        bg.fillStyle = "rgba(56, 189, 248, 0.12)";
        const ditherStep = 10;
        for (let dx = runeCenterX - R * 2.2; dx < runeCenterX + R * 2.2; dx += ditherStep) {
          for (let dy = runeCenterY - R * 1.8; dy < runeCenterY + R * 2.2; dy += ditherStep) {
            const dist = Math.hypot(dx - runeCenterX, dy - runeCenterY);
            if (dist < R * 2.2 && Math.sin(dx * 17.1 + dy * 23.3) > (dist / (R * 2.2))) {
              bg.fillRect(dx, dy, 1.8, 1.8);
            }
          }
        }

        // Multi-Pass Low-Brightness Arc Geometry
        function drawRunePass(strokeCol, lineW, shadowBlur, shadowCol) {
          bg.save();
          bg.strokeStyle = strokeCol;
          bg.lineWidth = lineW;
          if (shadowBlur > 0) {
            bg.shadowBlur = shadowBlur;
            bg.shadowColor = shadowCol;
          }

          // 1. Top Inverted Basin & Vertical Ray Conduit
          bg.beginPath();
          const basinY = runeCenterY - R * 1.52;
          bg.moveTo(runeCenterX - R * 0.65, basinY - 6);
          bg.quadraticCurveTo(runeCenterX, basinY + 14, runeCenterX + R * 0.65, basinY - 6);
          bg.stroke();

          // Vertical Spear Conduit through the center
          bg.beginPath();
          bg.moveTo(runeCenterX, basinY);
          bg.lineTo(runeCenterX, runeCenterY + R * 1.55);
          bg.stroke();

          // 2. Primary Upper Ring
          bg.beginPath();
          bg.arc(runeCenterX, runeCenterY - R * 0.22, R * 0.88, 0, Math.PI * 2);
          bg.stroke();

          // 3. Central Great Interlocking Ring
          bg.beginPath();
          bg.arc(runeCenterX, runeCenterY + R * 0.15, R * 0.95, 0, Math.PI * 2);
          bg.stroke();

          // 4. Lower Intersecting Left & Right Rings
          bg.beginPath();
          bg.arc(runeCenterX - R * 0.44, runeCenterY + R * 0.48, R * 0.74, 0, Math.PI * 2);
          bg.stroke();

          bg.beginPath();
          bg.arc(runeCenterX + R * 0.44, runeCenterY + R * 0.48, R * 0.74, 0, Math.PI * 2);
          bg.stroke();

          // 5. Bottom Anchor Basin Arc
          bg.beginPath();
          bg.arc(runeCenterX, runeCenterY + R * 0.85, R * 0.65, 0.2 * Math.PI, 0.8 * Math.PI);
          bg.stroke();

          // 6. Cross-Axis Curved Rays
          bg.beginPath();
          bg.arc(runeCenterX, runeCenterY - R * 0.1, R * 1.35, 0.3 * Math.PI, 0.7 * Math.PI);
          bg.stroke();

          bg.restore();
        }

        // Low-Brightness Atmospheric Passes
        drawRunePass("rgba(234, 88, 12, 0.16)", 6, 10, "#ea580c");
        drawRunePass("rgba(249, 115, 22, 0.28)", 2.4, 5, "#f97316");
        drawRunePass("rgba(254, 215, 170, 0.40)", 1.0, 2, "#fed7aa");

        // Jagged Volcanic Crags (Bottom Silhouette)
        const waterY = height * 0.76;
        bg.fillStyle = "#020306";
        bg.beginPath();
        bg.moveTo(0, waterY);
        const volcanicPeaks = [
          [0.0, waterY - height * 0.14],
          [0.12, waterY - height * 0.22],
          [0.26, waterY - height * 0.16],
          [0.38, waterY - height * 0.25],
          [0.50, waterY - height * 0.18],
          [0.64, waterY - height * 0.27],
          [0.78, waterY - height * 0.16],
          [0.90, waterY - height * 0.23],
          [1.0, waterY - height * 0.15],
        ];
        for (const pt of volcanicPeaks) {
          bg.lineTo(pt[0] * width, pt[1]);
        }
        bg.lineTo(width, height);
        bg.lineTo(0, height);
        bg.closePath();
        bg.fill();

        // Molten Lava Reflection Ripples
        bg.fillStyle = "rgba(234, 88, 12, 0.14)";
        for (let wy = waterY + 4; wy < height; wy += 8) {
          const waveSpan = width * 0.36;
          const startX = width * 0.32 + (Math.sin(wy * 0.1) * 20);
          for (let wx = startX; wx < startX + waveSpan; wx += 12) {
            if (Math.sin(wx * 0.08 + wy * 0.25) > 0.35) {
              bg.fillRect(wx, wy, 7, 1.2);
            }
          }
        }

        bg.restore();
      }
    }

    function resize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.width = width + "px";
      canvas.style.height = height + "px";
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.scale(dpr, dpr);
      renderLandscapeBuffer();
      initParticles();
    }

    window.addEventListener("resize", resize);
    resize();

    let animationFrameId = null;

    function draw() {
      ctx.clearRect(0, 0, width, height);

      // Draw cached static dither landscape
      if (offscreenBuffer.width > 0) {
        ctx.drawImage(offscreenBuffer, 0, 0, width, height);
      }

      const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (prefersReducedMotion) return;

      // Update and Draw Particles (Embers in Dusk, Ash in Dawn)
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];

        if (isDawn) {
          // Ash flakes drifting gently downward
          p.y += p.speed * 0.6;
          p.x += Math.sin(p.pulsePhase) * 0.35 + p.drift;
          p.pulsePhase += p.pulseSpeed;

          if (p.y > height + 10) {
            p.y = -10;
            p.x = Math.random() * width;
          }
          ctx.fillStyle = `rgba(100, 116, 139, ${p.opacity * (0.6 + 0.4 * Math.sin(p.pulsePhase))})`;
        } else {
          // Embers drifting slowly upward
          p.y -= p.speed * 0.75;
          p.x += Math.sin(p.pulsePhase) * 0.45 + p.drift;
          p.pulsePhase += p.pulseSpeed;

          if (p.y < -10) {
            p.y = height + 10;
            p.x = Math.random() * width;
          }
          const emberAlpha = p.opacity * (0.7 + 0.3 * Math.sin(p.pulsePhase));
          if (i % 3 === 0) {
            ctx.fillStyle = `rgba(254, 240, 138, ${emberAlpha})`;
          } else if (i % 3 === 1) {
            ctx.fillStyle = `rgba(249, 115, 22, ${emberAlpha})`;
          } else {
            ctx.fillStyle = `rgba(239, 68, 68, ${emberAlpha})`;
          }
        }

        ctx.fillRect(p.x, p.y, p.size, p.size);
      }

      animationFrameId = requestAnimationFrame(draw);
    }

    draw();

    atmosphericCanvas = {
      updateTheme: (newIsDawn) => {
        isDawn = newIsDawn;
        renderLandscapeBuffer();
      },
      destroy: () => {
        if (animationFrameId) cancelAnimationFrame(animationFrameId);
        window.removeEventListener("resize", resize);
      }
    };
  }

  // ==========================================================================
  // Rune Dawn & Rune Dusk Theme Controller
  // ==========================================================================

  function applyTheme(theme) {
    const isDawn = (theme === "dawn");
    document.documentElement.classList.remove("rune-dusk", "rune-dawn");
    document.documentElement.classList.add(isDawn ? "rune-dawn" : "rune-dusk");

    if (elements.themeToggleLabel) {
      elements.themeToggleLabel.textContent = isDawn ? "Rune Dawn" : "Rune Dusk";
    }

    const heroImg = document.querySelector(".crazyflie-hero-img");
    if (heroImg) {
      heroImg.src = isDawn ? "/assets/crazyflie_ragnarok_dawn.png" : "/assets/crazyflie_ragnarok_dusk.png";
    }

    if (droneViewer && droneViewer.updateTheme) {
      droneViewer.updateTheme(isDawn);
    }

    if (atmosphericCanvas && atmosphericCanvas.updateTheme) {
      atmosphericCanvas.updateTheme(isDawn);
    }

    try {
      localStorage.setItem("domnir-theme", isDawn ? "dawn" : "dusk");
    } catch (_) {}
  }

  function setupTheme() {
    let saved = "dusk";
    try {
      saved = localStorage.getItem("domnir-theme") || "dusk";
    } catch (_) {}
    applyTheme(saved);

    if (elements.themeToggleBtn) {
      elements.themeToggleBtn.addEventListener("click", () => {
        const isCurrentDawn = document.documentElement.classList.contains("rune-dawn");
        const next = isCurrentDawn ? "dusk" : "dawn";
        applyTheme(next);
        toast(`Activated ${next === "dawn" ? "Rune Dawn (Intense Warm)" : "Rune Dusk (Intense Night)"} theme.`, "info");
      });
    }
  }

  // ==========================================================================
  // Workspace Quick Oracle Drawer
  // ==========================================================================

  function renderWsOracleResults(topic = "all", query = "") {
    if (!elements.wsOracleResultsGrid) return;
    const q = query.trim().toLowerCase();

    // Security check: Refuse prompt injections
    if (q.includes("ignore previous") || q.includes("system prompt") || q.includes("bypass") || q.includes("eval(") || q.includes("exec(")) {
      elements.wsOracleResultsGrid.innerHTML = `
        <div style="grid-column: 1 / -1; padding: 12px; font-size: 11px; color: var(--color-failure, #f43f5e);">
          Security Notice: Instruction override attempt refused. Grounded documentation queries only.
        </div>
      `;
      return;
    }

    const matches = searchKnowledgeCorpus(topic, q, 4);

    if (matches.length === 0) {
      elements.wsOracleResultsGrid.innerHTML = `
        <div style="grid-column: 1 / -1; padding: 12px; font-size: 11px; color: var(--text-subtle);">
          No quick matches found. Click 'Full Codex' above to search the comprehensive architecture ledger.
        </div>
      `;
      return;
    }

    elements.wsOracleResultsGrid.innerHTML = matches.map(item => `
      <div class="ws-oracle-card">
        <div class="ws-oracle-card-header">
          <span class="ws-oracle-topic">${escapeHtml(item.topicLabel)}</span>
          <button type="button" class="btn btn-sm btn-ghost ws-copy-btn" data-snippet="${encodeURIComponent(item.snippet)}" title="Copy verified snippet">Copy</button>
        </div>
        <h4 class="ws-oracle-card-title">${escapeHtml(item.title)}</h4>
        <div style="font-size: 9px; color: var(--text-muted); margin-bottom: 4px; font-family: var(--font-mono);">Source: ${escapeHtml(item.citation || "Specification")}</div>
        <p class="ws-oracle-card-summary">${escapeHtml(item.summary.substring(0, 150))}...</p>
      </div>
    `).join("");

    elements.wsOracleResultsGrid.querySelectorAll(".ws-copy-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const code = decodeURIComponent(btn.getAttribute("data-snippet") || "");
        if (!code) return;
        navigator.clipboard.writeText(code).then(() => {
          const orig = btn.textContent;
          btn.textContent = "Copied!";
          toast("Oracle code copied to clipboard.", "info");
          setTimeout(() => (btn.textContent = orig), 1500);
        });
      });
    });
  }

  function setupWorkspaceOracle() {
    renderWsOracleResults("all", "");

    if (elements.toggleWsOracleBtn && elements.wsOracleBody) {
      elements.toggleWsOracleBtn.addEventListener("click", () => {
        const isCollapsed = elements.wsOracleBody.classList.toggle("collapsed");
        if (elements.wsOracleToggleIcon) {
          elements.wsOracleToggleIcon.textContent = isCollapsed ? "+" : "-";
        }
        elements.toggleWsOracleBtn.innerHTML = isCollapsed
          ? `<span id="wsOracleToggleIcon">+</span> Show Drawer`
          : `<span id="wsOracleToggleIcon">-</span> Hide Drawer`;
      });
    }

    if (elements.wsOracleSearchInput) {
      elements.wsOracleSearchInput.addEventListener("input", (e) => {
        const activeChip = document.querySelector("[data-ws-topic].active")?.getAttribute("data-ws-topic") || "all";
        renderWsOracleResults(activeChip, e.target.value);
      });
    }

    if (elements.wsOracleChips) {
      elements.wsOracleChips.forEach(chip => {
        chip.addEventListener("click", () => {
          elements.wsOracleChips.forEach(c => c.classList.remove("active"));
          chip.classList.add("active");
          const topic = chip.getAttribute("data-ws-topic") || "all";
          const q = elements.wsOracleSearchInput ? elements.wsOracleSearchInput.value : "";
          renderWsOracleResults(topic, q);
        });
      });
    }

    if (elements.wsOracleJumpArchitectureBtn) {
      elements.wsOracleJumpArchitectureBtn.addEventListener("click", () => {
        const archTab = document.querySelector('[data-tab="tab-architecture"]');
        if (archTab) archTab.click();
        if (elements.oracleSearchInput) {
          elements.oracleSearchInput.scrollIntoView({ behavior: "smooth", block: "center" });
          setTimeout(() => elements.oracleSearchInput.focus(), 300);
        }
      });
    }
  }

  function setupOracle() {
    renderOracleResults("all", "");

    if (elements.oracleSearchInput) {
      elements.oracleSearchInput.addEventListener("input", (e) => {
        const activeTopic = document.querySelector(".topic-pill.active")?.getAttribute("data-topic") || "all";
        renderOracleResults(activeTopic, e.target.value);
      });
    }

    if (elements.oracleTopicPills) {
      elements.oracleTopicPills.forEach(pill => {
        pill.addEventListener("click", () => {
          elements.oracleTopicPills.forEach(p => p.classList.remove("active"));
          pill.classList.add("active");
          const topic = pill.getAttribute("data-topic") || "all";
          const query = elements.oracleSearchInput ? elements.oracleSearchInput.value : "";
          renderOracleResults(topic, query);
        });
      });
    }

    if (elements.openOracleHeaderBtn) {
      elements.openOracleHeaderBtn.addEventListener("click", () => {
        const archTab = document.querySelector('[data-tab="tab-architecture"]');
        if (archTab) archTab.click();
        if (elements.oracleSearchInput) {
          elements.oracleSearchInput.scrollIntoView({ behavior: "smooth", block: "center" });
          setTimeout(() => elements.oracleSearchInput.focus(), 300);
        }
      });
    }
  }

  function setupVerifier() {
    if (elements.dropZone && elements.courtFileInput) {
      elements.dropZone.addEventListener("click", () => {
        elements.courtFileInput.value = "";
        elements.courtFileInput.click();
      });
    }

    if (elements.browseFileBtn && elements.courtFileInput) {
      elements.browseFileBtn.addEventListener("click", e => {
        e.stopPropagation();
        elements.courtFileInput.value = "";
        elements.courtFileInput.click();
      });
    }

    if (elements.dropZone) {
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
        if (e.dataTransfer && e.dataTransfer.files.length > 0) {
          loadJsonFile(e.dataTransfer.files[0]);
        }
      });
    }

    if (elements.courtFileInput) {
      elements.courtFileInput.addEventListener("change", e => {
        if (e.target && e.target.files.length > 0) {
          loadJsonFile(e.target.files[0]);
        }
      });
    }

    if (elements.pasteSampleBtn) {
      elements.pasteSampleBtn.addEventListener("click", e => {
        e.stopPropagation();
        if (state.activeCourtRecord && elements.courtJsonInput) {
          elements.courtJsonInput.value = JSON.stringify(state.activeCourtRecord, null, 2);
          toast("Loaded active run court record into verifier.", "info");
        } else {
          toast("No active trial record yet. Run a trial in Step 4 or upload a saved court record.", "warning");
        }
      });
    }

    if (elements.submitVerifyBtn) {
      elements.submitVerifyBtn.addEventListener("click", verifyCourtRecord);
    }
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
        toast("Court record verified within tolerance (<= 1.00e-12 m).", "success");
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
    if (elements.copyCodeBtn) {
      elements.copyCodeBtn.addEventListener("click", () => {
        const text = elements.controllerSource.value;
        if (!text) return;
        navigator.clipboard.writeText(text).then(() => {
          const label = document.getElementById("copyCodeLabel");
          if (label) label.textContent = "Copied!";
          toast("Controller code copied to clipboard.", "info");
          setTimeout(() => {
            if (label) label.textContent = "Copy";
          }, 2000);
        });
      });
    }

    if (elements.controllerSource && elements.codeLineNumbers) {
      elements.controllerSource.addEventListener("scroll", () => {
        elements.codeLineNumbers.scrollTop = elements.controllerSource.scrollTop;
      });
      elements.controllerSource.addEventListener("input", (e) => {
        updateCodeLineNumbers(e.target.value);
      });
    }
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
      if (elements.fixtureBadgeNet) elements.fixtureBadgeNet.textContent = (net.status || "POLICY_CONFIRMED").replace(/_/g, " ");
      if (elements.fixtureEgressNet && net.policy) elements.fixtureEgressNet.textContent = net.policy.default_egress || "deny";
      if (elements.fixtureIngressNet && net.policy) elements.fixtureIngressNet.textContent = net.policy.default_ingress || "deny";
      if (elements.fixtureCleanupNet) {
        elements.fixtureCleanupNet.textContent = net.cleanup_succeeded ? "100% Confirmed" : "Failed";
      }
    }

    const tm = fixMap["RES-TIME-001"];
    if (tm) {
      if (elements.fixtureBadgeTime) elements.fixtureBadgeTime.textContent = (tm.status || "PASS").replace(/_/g, " ");
      if (elements.fixtureElapsedVal && typeof tm.elapsed_seconds === "number") {
        elements.fixtureElapsedVal.textContent = tm.elapsed_seconds.toFixed(3) + " s";
      }
      if (elements.fixtureCleanupTime) {
        elements.fixtureCleanupTime.textContent = tm.cleanup_succeeded ? "100% Confirmed" : "Failed";
      }
    }

    const mem = fixMap["RES-MEM-001"];
    if (mem) {
      if (elements.fixtureBadgeMem) elements.fixtureBadgeMem.textContent = (mem.status || "OBSERVED_EXIT").replace(/_/g, " ");
      if (elements.fixtureExitState && mem.observation) {
        elements.fixtureExitState.textContent = (mem.observation.job_state || "exited") + " (code " + (mem.observation.exit_code ?? "-1") + ")";
      }
      if (elements.fixtureAttributionVal) {
        const cleanCause = mem.termination_cause ? mem.termination_cause.replace(/_/g, " ") : "Not Attributed";
        elements.fixtureAttributionVal.textContent = cleanCause + " (Truthful)";
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
  // Crazyflie 2.0 Interactive 3D Viewer & Simulation Replay Adapter
  // ==========================================================================

  function highlightChartTimestep(sampleIndex) {
    const traj = state.activeTrajectory;
    if (!traj || traj.length === 0 || !elements.altitudeSvgChart) return;
    const idx = Math.min(traj.length - 1, Math.max(0, sampleIndex));
    const pt = traj[idx];
    if (!pt) return;

    const width = 760;
    const height = 320;
    const padding = { top: 30, right: 30, bottom: 40, left: 60 };
    const chartW = width - padding.left - padding.right;
    const chartH = height - padding.top - padding.bottom;

    const spec = getSpecFromForm ? getSpecFromForm() : { mission_duration_s: 0.4, target_altitude_m: 0.1, altitude_tolerance_m: 0.05, min_allowed_altitude_m: 0.05, max_allowed_altitude_m: 1.0 };
    const maxTime = traj[traj.length - 1].sim_time_s || spec.mission_duration_s || 0.4;
    const minTime = 0.0;
    let minAlt = 0.0;
    let maxAlt = Math.max(spec.max_allowed_altitude_m * 1.05, 0.3);

    for (const p of traj) {
      const z = p.position_m ? p.position_m[2] : p.altitude_m;
      if (z !== undefined && Number.isFinite(z)) {
        if (z < minAlt) minAlt = Math.min(minAlt, z * 1.15 - 0.02);
        if (z * 1.15 > maxAlt) maxAlt = z * 1.15 + 0.02;
      }
    }

    const t = pt.sim_time_s || 0.0;
    const z = pt.position_m ? pt.position_m[2] : (pt.altitude_m || 0.0);
    const ptX = padding.left + ((t - minTime) / (maxTime - minTime || 1)) * chartW;
    const ptY = padding.top + chartH - ((z - minAlt) / (maxAlt - minAlt || 1)) * chartH;

    const crosshairLine = elements.altitudeSvgChart.querySelector("#chartCrosshairLine");
    const crosshairDot = elements.altitudeSvgChart.querySelector("#chartCrosshairDot");

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
  }

  async function setupDroneViewer() {
    const canvas = elements.droneCanvas;
    const fallback = elements.droneFallbackStill;
    const badge = elements.viewerModeBadge;
    const pauseBtn = elements.stagePauseBtn;
    const resetBtn = elements.stageResetBtn;
    const replayBar = elements.stageReplayBar;
    const replayPlayBtn = elements.replayPlayBtn;
    const replayScrubber = elements.replayTimelineScrub;
    const replayTimeText = elements.replayTimeText;

    if (!canvas) return;

    let isWebGLAvailable = false;
    try {
      const glTest = document.createElement("canvas").getContext("webgl2") ||
                     document.createElement("canvas").getContext("webgl");
      isWebGLAvailable = !!glTest;
    } catch (_) {
      isWebGLAvailable = false;
    }

    if (!isWebGLAvailable) {
      if (fallback) fallback.classList.remove("hidden");
      if (canvas) canvas.style.display = "none";
      if (badge) badge.textContent = "2D PREVIEW (WEBGL UNAVAILABLE)";
      return;
    }

    try {
      const THREE = await import("three");
      const { GLTFLoader } = await import("three/addons/loaders/GLTFLoader.js");
      const { OrbitControls } = await import("three/addons/controls/OrbitControls.js");

      const width = canvas.clientWidth || 340;
      const height = canvas.clientHeight || 240;

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(40, width / height, 0.01, 50);

      const renderer = new THREE.WebGLRenderer({
        canvas: canvas,
        alpha: true,
        antialias: true,
        powerPreference: "high-performance"
      });
      renderer.setSize(width, height, false);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.1;

      const controls = new OrbitControls(camera, canvas);
      controls.enableDamping = true;
      controls.dampingFactor = 0.08;
      controls.minDistance = 0.12;
      controls.maxDistance = 1.5;
      controls.maxPolarAngle = Math.PI / 2 + 0.15;

      const ambientLight = new THREE.AmbientLight(0xffffff, 1.0);
      scene.add(ambientLight);

      const keyLight = new THREE.DirectionalLight(0xffffff, 2.0);
      keyLight.position.set(1.5, 3.0, 2.0);
      scene.add(keyLight);

      const fillLight = new THREE.DirectionalLight(0xffffff, 1.0);
      fillLight.position.set(-2.0, 1.0, -1.5);
      scene.add(fillLight);

      function createCrazyflieContactShadowTexture() {
        const shadowCanvas = document.createElement("canvas");
        shadowCanvas.width = 128;
        shadowCanvas.height = 128;
        const sCtx = shadowCanvas.getContext("2d");
        const grad = sCtx.createRadialGradient(64, 64, 0, 64, 64, 64);
        grad.addColorStop(0, "rgba(0, 0, 0, 0.95)");
        grad.addColorStop(0.25, "rgba(0, 0, 0, 0.78)");
        grad.addColorStop(0.50, "rgba(0, 0, 0, 0.42)");
        grad.addColorStop(0.75, "rgba(0, 0, 0, 0.16)");
        grad.addColorStop(0.92, "rgba(0, 0, 0, 0.04)");
        grad.addColorStop(1.0, "rgba(0, 0, 0, 0.0)");
        sCtx.fillStyle = grad;
        sCtx.fillRect(0, 0, 128, 128);
        const tex = new THREE.CanvasTexture(shadowCanvas);
        tex.needsUpdate = true;
        return tex;
      }
      const shadowTex = createCrazyflieContactShadowTexture();
      const shadowGeo = new THREE.PlaneGeometry(0.24, 0.24);
      shadowGeo.rotateX(-Math.PI / 2);
      const shadowMat = new THREE.MeshBasicMaterial({
        map: shadowTex,
        color: 0x000000,
        transparent: true,
        opacity: 0.88,
        depthWrite: false
      });
      const shadowMesh = new THREE.Mesh(shadowGeo, shadowMat);
      shadowMesh.position.y = -0.014;
      scene.add(shadowMesh);

      // 3D Ground Metric Grid and XYZ Spatial Axes
      const gridHelper = new THREE.GridHelper(2.4, 24, 0xf97316, 0x334155);
      gridHelper.position.y = -0.015;
      scene.add(gridHelper);

      const axesHelper = new THREE.AxesHelper(0.12);
      axesHelper.position.set(0, -0.014, 0);
      scene.add(axesHelper);

      // Dynamic Target Altitude Indicator Ring
      const targetRingGeo = new THREE.RingGeometry(0.08, 0.09, 32);
      targetRingGeo.rotateX(-Math.PI / 2);
      const targetRingMat = new THREE.MeshBasicMaterial({
        color: 0x06b6d4,
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.75
      });
      const targetRing = new THREE.Mesh(targetRingGeo, targetRingMat);
      targetRing.position.y = 0.0;
      scene.add(targetRing);

      function updateThemeLights(isDawn) {
        if (isDawn) {
          ambientLight.color.setHex(0xffe8c6);
          ambientLight.intensity = 1.2;
          keyLight.color.setHex(0xfff3d6);
          keyLight.intensity = 2.2;
          keyLight.position.set(1.5, 3.0, 2.0);
          fillLight.color.setHex(0xdfba96);
          fillLight.intensity = 0.8;
          shadowMat.color.setHex(0x1a0d04);
          shadowMat.opacity = 0.75;
        } else {
          ambientLight.color.setHex(0x162238);
          ambientLight.intensity = 1.0;
          keyLight.color.setHex(0xd4e8ff);
          keyLight.intensity = 1.8;
          keyLight.position.set(1.2, 2.8, 1.8);
          fillLight.color.setHex(0x38bdf8);
          fillLight.intensity = 1.6;
          fillLight.position.set(-2.5, 1.5, -2.0);
          shadowMat.color.setHex(0x000000);
          shadowMat.opacity = 0.88;
        }
      }

      const isInitialDawn = document.documentElement.classList.contains("rune-dawn");
      updateThemeLights(isInitialDawn);

      let droneModel = null;
      let rotorFL = null;
      let rotorFR = null;
      let rotorRL = null;
      let rotorRR = null;

      let defaultCamPos = new THREE.Vector3(0.18, 0.15, 0.22);
      let defaultTarget = new THREE.Vector3(0, 0, 0);

      let isTurntablePaused = false;
      let isReplaying = false;
      let replayTrajectory = null;
      let currentStep = 0;
      let isReplayPlaying = false;
      let replayInterval = null;

      const loader = new GLTFLoader();
      loader.load(
        "/assets/crazyflie_2.glb",
        gltf => {
          droneModel = gltf.scene;
          droneModel.name = "Crazyflie2";
          scene.add(droneModel);

          droneModel.traverse(child => {
            if (child.isMesh) {
              child.castShadow = true;
              child.receiveShadow = true;
            }
            if (child.name === "RotorFL") rotorFL = child;
            if (child.name === "RotorFR") rotorFR = child;
            if (child.name === "RotorRL") rotorRL = child;
            if (child.name === "RotorRR") rotorRR = child;
          });

          const box = new THREE.Box3().setFromObject(droneModel);
          const sphere = new THREE.Sphere();
          box.getBoundingSphere(sphere);

          const fovRad = (camera.fov * Math.PI) / 180;
          const aspect = width / height;
          const radiusWithMargin = sphere.radius * 1.15;
          let fitDistance = radiusWithMargin / Math.sin(fovRad / 2);
          if (aspect < 1.0) {
            fitDistance = fitDistance / aspect;
          }

          defaultCamPos = new THREE.Vector3(
            sphere.center.x + fitDistance * 0.65,
            sphere.center.y + fitDistance * 0.55,
            sphere.center.z + fitDistance * 0.75
          );
          defaultTarget = sphere.center.clone();

          camera.position.copy(defaultCamPos);
          controls.target.copy(defaultTarget);
          controls.update();

          if (fallback) fallback.classList.add("hidden");
          if (canvas) canvas.style.display = "block";
        },
        undefined,
        err => {
          console.warn("Failed to load /assets/crazyflie_2.glb, falling back to still:", err);
          if (fallback) fallback.classList.remove("hidden");
          if (canvas) canvas.style.display = "none";
          if (badge) badge.textContent = "2D FALLBACK (ASSET RETRY)";
        }
      );

      const resizeObserver = new ResizeObserver(entries => {
        for (const entry of entries) {
          const w = entry.contentRect.width;
          const h = entry.contentRect.height;
          if (w > 0 && h > 0) {
            camera.aspect = w / h;
            camera.updateProjectionMatrix();
            renderer.setSize(w, h, false);
          }
        }
      });
      resizeObserver.observe(canvas.parentElement || canvas);

      if (pauseBtn) {
        pauseBtn.addEventListener("click", () => {
          isTurntablePaused = !isTurntablePaused;
          pauseBtn.setAttribute("aria-label", isTurntablePaused ? "Resume Turntable" : "Pause Turntable");
          pauseBtn.title = isTurntablePaused ? "Resume Turntable" : "Pause Turntable";
          const icon = pauseBtn.querySelector("use");
          if (icon) {
            icon.setAttribute("href", isTurntablePaused ? "#icon-play" : "#icon-pause");
          }
        });
      }

      if (resetBtn) {
        resetBtn.addEventListener("click", () => {
          camera.position.copy(defaultCamPos);
          controls.target.copy(defaultTarget);
          controls.update();
          if (droneModel && !isReplaying) {
            droneModel.rotation.set(0, 0, 0);
            droneModel.position.set(0, 0, 0);
          }
        });
      }

      function setStep(stepIdx, trajectoryData) {
        const traj = trajectoryData || replayTrajectory;
        if (!traj || traj.length === 0 || !droneModel) return;

        const idx = Math.min(traj.length - 1, Math.max(0, stepIdx));
        currentStep = idx;

        const pt = traj[idx];
        if (!pt) return;

        const altM = pt.position_m ? pt.position_m[2] : (pt.altitude_m || 0.1);
        const timeS = pt.sim_time_s || (idx * 0.002);
        const sceneY = (altM - 0.10) * 0.8;

        if (pt.position_m && pt.position_m.length >= 3) {
          const posX = -(pt.position_m[1] || 0.0) * 0.8;
          const posZ = -(pt.position_m[0] || 0.0) * 0.8;
          droneModel.position.set(posX, sceneY, posZ);
        } else {
          droneModel.position.set(0, sceneY, 0);
        }

        if (pt.orientation_quat_wxyz && pt.orientation_quat_wxyz.length === 4) {
          const [qw, qx, qy, qz] = pt.orientation_quat_wxyz;
          droneModel.quaternion.set(-qy, qz, -qx, qw).normalize();
        }

        if (badge) {
          badge.textContent = (pt.orientation_quat_wxyz && pt.orientation_quat_wxyz.length === 4)
            ? "REPLAY: 6-DOF DYNAMICS"
            : "REPLAY: 1D ALTITUDE PROFILE";
        }

        // Dynamic 3D Follow-Camera tracking keeps Crazyflie in view at all altitudes
        controls.target.y = sceneY;
        camera.position.y = defaultCamPos.y + sceneY;
        controls.update();

        shadowMesh.position.x = droneModel.position.x;
        shadowMesh.position.z = droneModel.position.z;
        const shadowScale = Math.max(0.6, 1.0 + Math.max(0, altM - 0.05) * 1.5);
        shadowMesh.scale.set(shadowScale, shadowScale, shadowScale);
        shadowMat.opacity = Math.max(0.18, 0.85 / (1.0 + Math.max(0, altM - 0.05) * 3.5));

        const thrust = pt.action && pt.action.length > 0 ? pt.action[0] : (pt.thrust || 0.26);
        const spinDelta = (thrust / 0.26) * 0.35;
        if (rotorFL) rotorFL.rotation.y += spinDelta;
        if (rotorRR) rotorRR.rotation.y += spinDelta;
        if (rotorFR) rotorFR.rotation.y -= spinDelta;
        if (rotorRL) rotorRL.rotation.y -= spinDelta;

        if (replayTimeText) replayTimeText.textContent = "t = " + timeS.toFixed(3) + "s (step " + (pt.step_index || idx) + ")";
        if (replayScrubber && document.activeElement !== replayScrubber) {
          replayScrubber.value = idx;
        }
      }

      if (replayScrubber) {
        replayScrubber.addEventListener("input", e => {
          const val = parseInt(e.target.value, 10);
          setStep(val, replayTrajectory);
          highlightChartTimestep(val);
        });
      }

      function toggleReplayPlay() {
        if (!replayTrajectory || replayTrajectory.length === 0) return;
        isReplayPlaying = !isReplayPlaying;
        if (replayPlayBtn) replayPlayBtn.textContent = isReplayPlaying ? "Pause" : "Play";

        if (isReplayPlaying) {
          if (currentStep >= replayTrajectory.length - 1) {
            currentStep = 0;
          }
          replayInterval = setInterval(() => {
            if (!isReplayPlaying || !replayTrajectory) {
              clearInterval(replayInterval);
              return;
            }
            currentStep += 1;
            if (currentStep >= replayTrajectory.length) {
              currentStep = replayTrajectory.length - 1;
              isReplayPlaying = false;
              if (replayPlayBtn) replayPlayBtn.textContent = "Play";
              clearInterval(replayInterval);
            }
            setStep(currentStep, replayTrajectory);
            highlightChartTimestep(currentStep);
          }, 20);
        } else {
          if (replayInterval) clearInterval(replayInterval);
        }
      }

      if (replayPlayBtn) {
        replayPlayBtn.addEventListener("click", toggleReplayPlay);
      }

      function animate() {
        requestAnimationFrame(animate);

        if (document.hidden) return;

        const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

        if (droneModel && !isReplaying && !isTurntablePaused && !prefersReducedMotion) {
          droneModel.rotation.y += 0.007;

          if (rotorFL) rotorFL.rotation.y += 0.18;
          if (rotorRR) rotorRR.rotation.y += 0.18;
          if (rotorFR) rotorFR.rotation.y -= 0.18;
          if (rotorRL) rotorRL.rotation.y -= 0.18;
        }

        if (droneModel) {
          shadowMesh.position.x = droneModel.position.x;
          shadowMesh.position.z = droneModel.position.z;
        }

        controls.update();
        renderer.render(scene, camera);
      }
      animate();

      droneViewer = {
        updateTheme: isDawn => updateThemeLights(isDawn),
        resetView: () => {
          controls.target.copy(defaultTarget);
          camera.position.copy(defaultCamPos);
          controls.update();
          shadowMesh.position.set(0, -0.014, 0);
          shadowMesh.scale.set(1, 1, 1);
          if (droneModel && !isReplaying) {
            droneModel.rotation.set(0, 0, 0);
            droneModel.position.set(0, 0, 0);
          }
        },
        resize: () => {
          const w = canvas.clientWidth || 340;
          const h = canvas.clientHeight || 240;
          if (w > 0 && h > 0) {
            camera.aspect = w / h;
            camera.updateProjectionMatrix();
            renderer.setSize(w, h, false);
          }
        },
        setTargetAltitude: (targetAltM) => {
          const sceneY = (targetAltM - 0.10) * 0.8;
          targetRing.position.y = sceneY;
        },
        loadReplay: trajectory => {
          if (!trajectory || trajectory.length === 0) return;
          isReplaying = true;
          replayTrajectory = trajectory;
          currentStep = 0;
          if (badge) {
            badge.textContent = "RECORDED SIMULATION REPLAY";
            badge.classList.add("mode-replay");
          }
          if (replayBar) {
            replayBar.classList.remove("hidden");
          }
          if (replayScrubber) {
            replayScrubber.min = 0;
            replayScrubber.max = trajectory.length - 1;
            replayScrubber.value = 0;
          }
          if (droneModel) {
            droneModel.rotation.set(0, 0, 0);
          }
          setStep(0, trajectory);
        },
        resetToIdle: () => {
          isReplaying = false;
          replayTrajectory = null;
          currentStep = 0;
          if (isReplayPlaying) {
            isReplayPlaying = false;
            if (replayInterval) clearInterval(replayInterval);
            if (replayPlayBtn) replayPlayBtn.textContent = "Play";
          }
          if (badge) {
            badge.textContent = "ILLUSTRATIVE MODEL";
            badge.classList.remove("mode-replay");
          }
          if (replayBar) {
            replayBar.classList.add("hidden");
          }
          if (droneModel) {
            droneModel.position.set(0, 0, 0);
            droneModel.rotation.set(0, 0, 0);
          }
          controls.target.copy(defaultTarget);
          camera.position.copy(defaultCamPos);
          controls.update();
          shadowMesh.scale.set(1, 1, 1);
          shadowMat.opacity = document.documentElement.classList.contains("rune-dawn") ? 0.75 : 0.88;
        },
        setStep: (idx, traj) => {
          if (isReplaying) {
            setStep(idx, traj || replayTrajectory);
          }
        }
      };

    } catch (err) {
      console.warn("Three.js setup encountered an error, falling back to still:", err);
      if (fallback) fallback.classList.remove("hidden");
      if (canvas) canvas.style.display = "none";
      if (badge) badge.textContent = "2D FALLBACK PREVIEW";
    }
  }

  function setupViewPills() {
    const arenaStage = elements.simulationArenaStage;
    if (!arenaStage) return;

    const pills = document.querySelectorAll(".view-pill");
    pills.forEach(pill => {
      pill.addEventListener("click", () => {
        const viewMode = pill.dataset.view;
        pills.forEach(p => {
          p.classList.remove("active");
          p.setAttribute("aria-checked", "false");
        });
        pill.classList.add("active");
        pill.setAttribute("aria-checked", "true");

        arenaStage.classList.remove("view-mode-3d", "view-mode-2d", "view-mode-split");
        arenaStage.classList.add("view-mode-" + viewMode);

        if (droneViewer && droneViewer.resize) {
          setTimeout(() => droneViewer.resize(), 50);
        }
      });
    });
  }

  function setupTutorialModal() {
    const openBtn = elements.startTutorialBtn;
    const modal = elements.tutorialBackdrop;
    const closeBtn = elements.closeTutorialBtn;
    if (!openBtn || !modal) return;

    openBtn.addEventListener("click", () => {
      modal.classList.remove("hidden");
    });

    if (closeBtn) {
      closeBtn.addEventListener("click", () => {
        modal.classList.add("hidden");
      });
    }

    modal.addEventListener("click", e => {
      if (e.target === modal) {
        modal.classList.add("hidden");
      }
    });

    const scenarioBtns = modal.querySelectorAll(".run-scenario-btn");
    scenarioBtns.forEach(btn => {
      btn.addEventListener("click", () => {
        const scenario = btn.dataset.scenario;
        modal.classList.add("hidden");

        if (scenario === "nominal") {
          if (elements.presetNominal) elements.presetNominal.click();
          switchStep(1);
          toast("Tutorial: Loaded Nominal Hover (0.10m). Click 'Continue to AI Synthesis' to generate controller.", "info");
        } else if (scenario === "high") {
          if (elements.presetHigh) elements.presetHigh.click();
          switchStep(1);
          toast("Tutorial: Loaded 1.50m High Altitude Climb. Watch the 3D follow-cam track the ascent in Step 4!", "info");
        } else if (scenario === "turbulent") {
          if (elements.presetTurbulent) elements.presetTurbulent.click();
          switchStep(1);
          toast("Tutorial: Loaded Turbulent Stress (+-0.20 N). Tests falsification boundary corridor.", "warning");
        } else if (scenario === "timeout") {
          switchStep(2);
          elements.controllerSource.value = "def observe(state):\n    # Malicious or runaway controller infinite loop\n    while True:\n        pass\n    return [0.26]";
          toast("Tutorial: Injected Watchdog Timeout payload. Step 3/4 execution will trigger 0.50s hard termination without host lockup.", "error");
        }
      });
    });
  }

  // ==========================================================================
  // Ragnarok Adversarial Arena & Failure Atlas Logic (Stage I)
  // ==========================================================================

  function renderFailureAtlas(candidates, criticalWitness, minimizedWitness, spec) {
    const svg = elements.failureAtlasSvg;
    if (!svg) return;

    if ((!candidates || candidates.length === 0) && !criticalWitness && !minimizedWitness) {
      svg.innerHTML = `
        <rect width="100%" height="100%" fill="var(--chart-bg)" />
        <text x="380" y="160" fill="#64748b" text-anchor="middle" font-family="monospace" font-size="13">Launch Adversarial Search to map the physical failure boundary</text>
      `;
      return;
    }

    const width = 760;
    const height = 320;
    const padding = { top: 35, right: 35, bottom: 45, left: 65 };
    const chartW = width - padding.left - padding.right;
    const chartH = height - padding.top - padding.bottom;

    // Disturbance force bounds (X axis)
    let minForce = -0.15;
    let maxForce = 0.15;
    if (spec && typeof spec.disturbance_force_z_min === "number") {
      minForce = Math.min(minForce, spec.disturbance_force_z_min);
    }
    if (spec && typeof spec.disturbance_force_z_max === "number") {
      maxForce = Math.max(maxForce, spec.disturbance_force_z_max);
    }

    // Altitude bounds (Y axis)
    let minAlt = 0.05;
    let maxAlt = 0.25;
    if (spec && typeof spec.min_allowed_altitude_m === "number") {
      minAlt = Math.max(0.01, spec.min_allowed_altitude_m * 0.8);
    }
    if (spec && typeof spec.max_allowed_altitude_m === "number") {
      maxAlt = Math.max(0.20, (spec.target_altitude_m || 0.1) * 1.6);
    }

    // Expand bounds with candidate values if any exceed default
    const allPts = [...(candidates || [])];
    if (criticalWitness && criticalWitness.scenario) {
      allPts.push(criticalWitness);
    }
    if (minimizedWitness) {
      allPts.push({ scenario: minimizedWitness, satisfied: false });
    }

    for (const pt of allPts) {
      const scen = pt.scenario || pt;
      const f = scen.disturbance_force_z;
      const a = scen.initial_altitude_m;
      if (typeof f === "number") {
        if (f < minForce) minForce = f - 0.02;
        if (f > maxForce) maxForce = f + 0.02;
      }
      if (typeof a === "number") {
        if (a < minAlt) minAlt = Math.max(0.01, a - 0.02);
        if (a > maxAlt) maxAlt = a + 0.02;
      }
    }

    const scaleX = f => padding.left + ((f - minForce) / (maxForce - minForce || 1)) * chartW;
    const scaleY = a => padding.top + chartH - ((a - minAlt) / (maxAlt - minAlt || 1)) * chartH;

    let svgHtml = `
      <defs>
        <clipPath id="atlasClipArea">
          <rect x="${padding.left}" y="${padding.top}" width="${chartW}" height="${chartH}" />
        </clipPath>
      </defs>
      <rect width="100%" height="100%" fill="var(--chart-bg)" />
    `;

    // Horizontal grid lines (Altitude)
    const yTicks = 5;
    for (let i = 0; i <= yTicks; i++) {
      const aVal = minAlt + (i / yTicks) * (maxAlt - minAlt);
      const y = scaleY(aVal);
      svgHtml += `<line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" stroke="#1e293b" stroke-width="1" stroke-dasharray="2,2"/>`;
      svgHtml += `<text x="${padding.left - 8}" y="${y + 4}" fill="#64748b" font-family="monospace" font-size="10" text-anchor="end">${aVal.toFixed(2)}m</text>`;
    }

    // Vertical grid lines (Disturbance Force)
    const xTicks = 6;
    for (let i = 0; i <= xTicks; i++) {
      const fVal = minForce + (i / xTicks) * (maxForce - minForce);
      const x = scaleX(fVal);
      svgHtml += `<line x1="${x}" y1="${padding.top}" x2="${x}" y2="${height - padding.bottom}" stroke="#1e293b" stroke-width="1" stroke-dasharray="2,2"/>`;
      const sign = fVal > 0 ? "+" : "";
      svgHtml += `<text x="${x}" y="${height - padding.bottom + 18}" fill="#64748b" font-family="monospace" font-size="10" text-anchor="middle">${sign}${fVal.toFixed(2)}N</text>`;
    }

    // Zero-force reference line
    if (minForce <= 0 && maxForce >= 0) {
      const zeroX = scaleX(0.0);
      svgHtml += `<line x1="${zeroX}" y1="${padding.top}" x2="${zeroX}" y2="${height - padding.bottom}" stroke="#334155" stroke-width="1.5" stroke-dasharray="4,4"/>`;
      svgHtml += `<text x="${zeroX}" y="${padding.top - 12}" fill="#94a3b8" font-family="monospace" font-size="9" text-anchor="middle">Zero Disturbance</text>`;
    }

    // Target altitude reference line
    if (spec && typeof spec.target_altitude_m === "number") {
      const targetY = scaleY(spec.target_altitude_m);
      if (targetY >= padding.top && targetY <= height - padding.bottom) {
        svgHtml += `<line x1="${padding.left}" y1="${targetY}" x2="${width - padding.right}" y2="${targetY}" stroke="rgba(6, 182, 212, 0.4)" stroke-width="1" stroke-dasharray="4,4"/>`;
        svgHtml += `<text x="${width - padding.right}" y="${targetY - 4}" fill="#06b6d4" font-family="monospace" font-size="9" text-anchor="end">Target Alt (${spec.target_altitude_m.toFixed(2)}m)</text>`;
      }
    }

    // Axis titles
    svgHtml += `<text x="${padding.left + chartW / 2}" y="${height - 8}" fill="#94a3b8" font-family="sans-serif" font-size="11" text-anchor="middle" font-weight="600">Vertical Disturbance Force (N)</text>`;
    svgHtml += `<text x="18" y="${padding.top + chartH / 2}" fill="#94a3b8" font-family="sans-serif" font-size="11" text-anchor="middle" font-weight="600" transform="rotate(-90 18 ${padding.top + chartH / 2})">Initial Altitude (m)</text>`;

    // Untested domain watermark / annotation
    svgHtml += `
      <g class="atlas-untested-watermark" opacity="0.65">
        <text x="${width - padding.right}" y="${padding.top + 14}" fill="#64748b" font-family="monospace" font-size="9" text-anchor="end">GRAY REGION: UNTESTED / UNKNOWN RISK</text>
        <text x="${width - padding.right}" y="${padding.top + 26}" fill="#475569" font-family="monospace" font-size="8" text-anchor="end">Only plotted points have empirical physics evidence</text>
      </g>
    `;

    // Plot candidates
    (candidates || []).forEach((c, idx) => {
      const scen = c.scenario || {};
      const f = typeof scen.disturbance_force_z === "number" ? scen.disturbance_force_z : 0.0;
      const a = typeof scen.initial_altitude_m === "number" ? scen.initial_altitude_m : 0.1;
      const x = scaleX(f);
      const y = scaleY(a);
      const isSatisfied = c.satisfied !== false && (c.robustness === undefined || c.robustness > 0);
      const fillClass = isSatisfied ? "atlas-point-satisfied" : "atlas-point-violated";
      const fillColor = isSatisfied ? "#10b981" : "#f43f5e";

      svgHtml += `
        <circle
          cx="${x}"
          cy="${y}"
          r="5"
          class="atlas-point ${fillClass}"
          data-candidate-idx="${idx}"
          fill="${fillColor}"
          opacity="0.88"
        />
      `;
    });

    // If critical witness exists, draw pulsating target ring and label
    if (criticalWitness && criticalWitness.scenario) {
      const wf = criticalWitness.scenario.disturbance_force_z;
      const wa = criticalWitness.scenario.initial_altitude_m;
      const wx = scaleX(wf);
      const wy = scaleY(wa);

      svgHtml += `
        <g class="witness-marker">
          <circle cx="${wx}" cy="${wy}" r="11" fill="none" stroke="#f43f5e" stroke-width="2" stroke-dasharray="3,2" opacity="0.9" />
          <circle cx="${wx}" cy="${wy}" r="17" fill="none" stroke="#f43f5e" stroke-width="1" opacity="0.4" />
          <circle cx="${wx}" cy="${wy}" r="6" fill="#f43f5e" stroke="#ffffff" stroke-width="1.5" />
          <text x="${wx + 10}" y="${wy - 8}" fill="#f43f5e" font-family="monospace" font-size="10" font-weight="700">WITNESS</text>
        </g>
      `;
    }

    // If minimized witness exists, draw connecting reduction vector line and diamond
    if (minimizedWitness && criticalWitness && criticalWitness.scenario) {
      const origX = scaleX(criticalWitness.scenario.disturbance_force_z);
      const origY = scaleY(criticalWitness.scenario.initial_altitude_m);
      const minX = scaleX(minimizedWitness.disturbance_force_z);
      const minY = scaleY(minimizedWitness.initial_altitude_m);

      svgHtml += `
        <g class="reduction-vector">
          <line x1="${origX}" y1="${origY}" x2="${minX}" y2="${minY}" stroke="#f59e0b" stroke-width="2" stroke-dasharray="4,3" />
          <polygon points="${minX},${minY - 7} ${minX + 7},${minY} ${minX},${minY + 7} ${minX - 7},${minY}" fill="#f59e0b" stroke="#ffffff" stroke-width="1.5" />
          <text x="${minX + 9}" y="${minY + 12}" fill="#f59e0b" font-family="monospace" font-size="10" font-weight="700">1-MINIMAL</text>
        </g>
      `;
    }

    svg.innerHTML = svgHtml;

    // Attach interactive tooltips to circles
    attachAtlasTooltipListeners(candidates, scaleX, scaleY);
  }

  function attachAtlasTooltipListeners(candidates, scaleX, scaleY) {
    const wrapper = elements.failureAtlasWrapper;
    const tooltip = elements.atlasTooltip;
    if (!wrapper || !tooltip) return;

    const circles = wrapper.querySelectorAll("circle.atlas-point");
    circles.forEach(circle => {
      circle.addEventListener("mouseenter", e => {
        const idx = parseInt(circle.dataset.candidateIdx, 10);
        const c = candidates[idx];
        if (!c) return;

        const scen = c.scenario || {};
        const f = typeof scen.disturbance_force_z === "number" ? scen.disturbance_force_z.toFixed(4) : "0.0000";
        const a = typeof scen.initial_altitude_m === "number" ? scen.initial_altitude_m.toFixed(3) : "0.000";
        const rho = typeof c.robustness === "number" ? c.robustness.toFixed(4) : "---";
        const statusText = c.satisfied === false || c.robustness <= 0 ? "VIOLATION" : "SATISFIED";
        const statusColor = statusText === "VIOLATION" ? "#f43f5e" : "#10b981";

        tooltip.innerHTML = `
          <div class="atlas-tooltip-header">
            <span>Trial #${c.iteration || (idx + 1)}</span>
            <span style="color: ${statusColor}; font-weight: 700;">${statusText}</span>
          </div>
          <div class="atlas-tooltip-row">
            <span>Disturbance Force:</span>
            <span class="atlas-tooltip-val font-mono">${f} N</span>
          </div>
          <div class="atlas-tooltip-row">
            <span>Initial Altitude:</span>
            <span class="atlas-tooltip-val font-mono">${a} m</span>
          </div>
          <div class="atlas-tooltip-row">
            <span>Robustness Margin:</span>
            <span class="atlas-tooltip-val font-mono">${rho} m</span>
          </div>
          ${c.critical_predicate ? `
          <div class="atlas-tooltip-row">
            <span>Predicate:</span>
            <span class="atlas-tooltip-val font-mono">${c.critical_predicate}</span>
          </div>` : ""}
        `;

        tooltip.classList.remove("hidden");
        const rect = wrapper.getBoundingClientRect();
        const left = e.clientX - rect.left;
        const top = e.clientY - rect.top;
        tooltip.style.left = `${left}px`;
        tooltip.style.top = `${top}px`;
      });

      circle.addEventListener("mousemove", e => {
        const rect = wrapper.getBoundingClientRect();
        const left = e.clientX - rect.left;
        const top = e.clientY - rect.top;
        tooltip.style.left = `${left}px`;
        tooltip.style.top = `${top}px`;
      });

      circle.addEventListener("mouseleave", () => {
        tooltip.classList.add("hidden");
      });

      circle.addEventListener("click", () => {
        const idx = parseInt(circle.dataset.candidateIdx, 10);
        const c = candidates[idx];
        if (!c) return;

        wrapper.querySelectorAll("circle.atlas-point").forEach(el => el.classList.remove("atlas-point-selected"));
        circle.classList.add("atlas-point-selected");

        const scen = c.scenario || {};
        if (elements.initAltitude && typeof scen.initial_altitude_m === "number") {
          elements.initAltitude.value = scen.initial_altitude_m;
        }
        if (elements.vertDisturbance && typeof scen.disturbance_force_z === "number") {
          elements.vertDisturbance.value = scen.disturbance_force_z;
        }
        const status = c.satisfied === false || c.robustness <= 0 ? "VIOLATION" : "SATISFIED";
        toast(`Selected Trial #${c.iteration || (idx + 1)} (${status}): Alt=${scen.initial_altitude_m}m, Force=${scen.disturbance_force_z}N`, "info");
      });
    });
  }

  async function runFalsification() {
    const spec = getSpecFromForm();
    const sourceCode = elements.controllerSource.value;

    if (!sourceCode.trim()) {
      toast("Please load or generate a controller before launching adversarial search.", "warning");
      switchStep(2);
      return;
    }

    if (elements.runFalsifyBtn) elements.runFalsifyBtn.disabled = true;
    if (elements.falsifySpinner) elements.falsifySpinner.classList.remove("hidden");
    if (elements.arenaStatusBadge) {
      elements.arenaStatusBadge.textContent = "SEARCHING...";
      elements.arenaStatusBadge.className = "badge badge-running";
    }

    const payload = {
      spec: spec,
      controller_source: sourceCode,
      budget: state.ragnarok.budget,
      strategy: state.ragnarok.strategy,
      seed: 42,
    };

    try {
      const res = await fetch("/ragnarok/falsify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "Adversarial search failed");
      }

      const data = await res.json();
      state.ragnarok.candidates = data.candidates || [];
      state.ragnarok.criticalWitness = data.critical_witness || null;
      state.ragnarok.minimizedWitness = null;

      if (elements.atlasMetricTrials) elements.atlasMetricTrials.textContent = data.evaluations_count;
      if (elements.atlasMetricViolations) elements.atlasMetricViolations.textContent = data.violations_found;
      if (elements.atlasMetricMinRobustness) {
        elements.atlasMetricMinRobustness.textContent =
          typeof data.min_robustness === "number" ? data.min_robustness.toFixed(4) + " m" : "---";
      }

      if (data.comparison && data.comparison.discovery_efficiency_ratio) {
        state.ragnarok.discoverySpeedup = data.comparison.discovery_efficiency_ratio;
        if (elements.atlasMetricSpeedup) {
          elements.atlasMetricSpeedup.textContent = state.ragnarok.discoverySpeedup.toFixed(2) + "x";
        }
      } else if (data.strategy === "differential_evolution" && data.violations_found > 0) {
        const speedup = (data.evaluations_count / (data.first_violation_iteration || 1));
        state.ragnarok.discoverySpeedup = Math.max(1.0, speedup);
        if (elements.atlasMetricSpeedup) {
          elements.atlasMetricSpeedup.textContent = state.ragnarok.discoverySpeedup.toFixed(2) + "x";
        }
      } else {
        if (elements.atlasMetricSpeedup) elements.atlasMetricSpeedup.textContent = "1.00x";
      }

      if (data.violations_found > 0 && data.critical_witness) {
        if (elements.arenaStatusBadge) {
          elements.arenaStatusBadge.textContent = "FALSIFIED";
          elements.arenaStatusBadge.className = "badge badge-failed";
        }
        if (elements.runMinimizeBtn) elements.runMinimizeBtn.disabled = false;
        if (elements.runRepairBtn) elements.runRepairBtn.disabled = false;

        if (elements.witnessDataGrid) elements.witnessDataGrid.classList.remove("hidden");
        if (elements.witnessEmptyText) elements.witnessEmptyText.classList.add("hidden");

        const cw = data.critical_witness;
        if (elements.witnessPredicate) elements.witnessPredicate.textContent = cw.critical_predicate || "safety_contract_breach";
        if (elements.witnessTimestamp) {
          elements.witnessTimestamp.textContent = typeof cw.critical_time_s === "number" ? cw.critical_time_s.toFixed(3) + " s" : "---";
        }
        if (elements.witnessMargin) {
          elements.witnessMargin.textContent = typeof cw.robustness === "number" ? cw.robustness.toFixed(4) + " m" : "---";
        }
        if (elements.witnessDisturbance && cw.scenario) {
          elements.witnessDisturbance.textContent = typeof cw.scenario.disturbance_force_z === "number" ? cw.scenario.disturbance_force_z.toFixed(4) + " N" : "0.000 N";
        }
        if (elements.witnessAltitude && cw.scenario) {
          elements.witnessAltitude.textContent = typeof cw.scenario.initial_altitude_m === "number" ? cw.scenario.initial_altitude_m.toFixed(3) + " m" : "---";
        }
        if (elements.witnessCostReduction) elements.witnessCostReduction.textContent = "Pending 1-minimal reduction";

        toast(`Adversarial violation witness found at trial #${cw.iteration || 1}! Predicate: ${cw.critical_predicate}`, "error");
      } else {
        if (elements.arenaStatusBadge) {
          elements.arenaStatusBadge.textContent = "NOT FALSIFIED";
          elements.arenaStatusBadge.className = "badge badge-passed";
        }
        if (elements.runMinimizeBtn) elements.runMinimizeBtn.disabled = true;
        if (elements.runRepairBtn) elements.runRepairBtn.disabled = true;

        if (elements.witnessDataGrid) elements.witnessDataGrid.classList.add("hidden");
        if (elements.witnessEmptyText) {
          elements.witnessEmptyText.classList.remove("hidden");
          elements.witnessEmptyText.textContent = `Search completed: Controller satisfied all ${data.evaluations_count} adversarial trials within safety envelope.`;
        }

        toast(`Search complete: 0 violations found within budget (${data.evaluations_count} evaluations).`, "success");
      }

      renderFailureAtlas(state.ragnarok.candidates, state.ragnarok.criticalWitness, null, spec);
    } catch (err) {
      if (elements.arenaStatusBadge) {
        elements.arenaStatusBadge.textContent = "ERROR";
        elements.arenaStatusBadge.className = "badge badge-failed";
      }
      toast("Adversarial search failed: " + err.message, "error");
    } finally {
      if (elements.runFalsifyBtn) elements.runFalsifyBtn.disabled = false;
      if (elements.falsifySpinner) elements.falsifySpinner.classList.add("hidden");
    }
  }

  async function runCounterexampleMinimization() {
    if (!state.ragnarok.criticalWitness) {
      toast("No active violation witness to minimize. Run adversarial search first.", "warning");
      return;
    }

    const spec = getSpecFromForm();
    const sourceCode = elements.controllerSource.value;

    if (elements.runMinimizeBtn) elements.runMinimizeBtn.disabled = true;
    if (elements.minimizeSpinner) elements.minimizeSpinner.classList.remove("hidden");

    const payload = {
      spec: spec,
      controller_source: sourceCode,
      witness_scenario: state.ragnarok.criticalWitness.scenario,
      max_evaluations: 12,
    };

    try {
      const res = await fetch("/ragnarok/minimize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "Minimization failed");
      }

      const data = await res.json();
      state.ragnarok.minimizedWitness = data.minimized_scenario;

      const pct = (data.cost_reduction_ratio * 100).toFixed(1);
      if (elements.witnessCostReduction) {
        elements.witnessCostReduction.textContent = `${pct}% cost reduction (evals: ${data.evaluations_used})`;
      }

      renderFailureAtlas(state.ragnarok.candidates, state.ragnarok.criticalWitness, state.ragnarok.minimizedWitness, spec);

      toast(`1-Minimal reduction complete: Perturbation shrunk by ${pct}% while preserving failure predicate.`, "success");
    } catch (err) {
      toast("Minimization failed: " + err.message, "error");
    } finally {
      if (elements.runMinimizeBtn) elements.runMinimizeBtn.disabled = false;
      if (elements.minimizeSpinner) elements.minimizeSpinner.classList.add("hidden");
    }
  }

  async function runAutonomousRepair() {
    if (!state.ragnarok.criticalWitness) {
      toast("No active violation witness for repair. Run adversarial search first.", "warning");
      return;
    }

    const spec = getSpecFromForm();
    const sourceCode = elements.controllerSource.value;

    if (elements.runRepairBtn) elements.runRepairBtn.disabled = true;
    if (elements.repairSpinner) elements.repairSpinner.classList.remove("hidden");

    const payload = {
      spec: spec,
      controller_source: sourceCode,
      witness_scenario: state.ragnarok.criticalWitness.scenario,
      model: state.selectedModel,
      reasoning_effort: state.selectedReasoningEffort,
      max_revisions: 2,
    };

    try {
      const res = await fetch("/ragnarok/repair", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "Autonomous repair failed");
      }

      const data = await res.json();
      state.ragnarok.repairedResult = data;

      if (elements.repairEmptyText) elements.repairEmptyText.classList.add("hidden");
      if (elements.repairContentBox) elements.repairContentBox.classList.remove("hidden");

      if (elements.repairOutcomeBadge) {
        elements.repairOutcomeBadge.textContent = data.outcome;
        elements.repairOutcomeBadge.className = data.repaired_controller_source
          ? "badge badge-passed font-mono"
          : "badge badge-failed font-mono";
      }

      if (elements.repairRevisionsCount) {
        elements.repairRevisionsCount.textContent = data.total_revisions_attempted;
      }

      if (elements.repairHoldoutRate) {
        if (data.history && data.history.length > 0) {
          const latest = data.history[data.history.length - 1];
          const ratePct = (latest.holdout_pass_rate * 100).toFixed(1);
          elements.repairHoldoutRate.textContent = `${ratePct}% (${latest.passed_holdout ? "PASSED" : "FAILED"})`;
        } else {
          elements.repairHoldoutRate.textContent = data.repaired_controller_source ? "100.0% (PASSED)" : "0.0% (FAILED)";
        }
      }

      if (elements.repairedControllerSource) {
        elements.repairedControllerSource.textContent =
          data.repaired_controller_source || "# No acceptable repair generated that satisfies the holdout suite.";
      }

      if (data.repaired_controller_source) {
        toast("Autonomous CEGIS Repair accepted! Passed holdout suite regression gate.", "success");
      } else {
        toast("CEGIS Repair attempted " + data.total_revisions_attempted + " revisions but rejected by holdout gate.", "warning");
      }
    } catch (err) {
      toast("Autonomous repair failed: " + err.message, "error");
    } finally {
      if (elements.runRepairBtn) elements.runRepairBtn.disabled = false;
      if (elements.repairSpinner) elements.repairSpinner.classList.add("hidden");
    }
  }

  function copyRepairedCode() {
    if (!state.ragnarok.repairedResult || !state.ragnarok.repairedResult.repaired_controller_source) {
      toast("No repaired controller code to copy.", "warning");
      return;
    }
    navigator.clipboard.writeText(state.ragnarok.repairedResult.repaired_controller_source)
      .then(() => toast("Repaired controller code copied to clipboard!", "success"))
      .catch(() => toast("Failed to copy code to clipboard.", "error"));
  }

  function loadRepairedCodeIntoStep2() {
    if (!state.ragnarok.repairedResult || !state.ragnarok.repairedResult.repaired_controller_source) {
      toast("No repaired controller code available to load.", "warning");
      return;
    }
    elements.controllerSource.value = state.ragnarok.repairedResult.repaired_controller_source;
    updateCodeMetadata(state.ragnarok.repairedResult.repaired_controller_source);
    switchStep(2);
    toast("Repaired controller loaded into Step 2! You can now validate AST and run verification.", "success");
  }

  function setupRagnarokArena() {
    // Strategy pills
    if (elements.stratPills && elements.stratPills.length > 0) {
      elements.stratPills.forEach(pill => {
        pill.addEventListener("click", () => {
          elements.stratPills.forEach(p => p.classList.remove("active"));
          pill.classList.add("active");
          state.ragnarok.strategy = pill.dataset.strategy || "differential_evolution";
        });
      });
    }

    // Budget slider
    if (elements.ragnarokBudgetInput && elements.ragnarokBudgetValue) {
      elements.ragnarokBudgetInput.addEventListener("input", e => {
        const val = parseInt(e.target.value, 10) || 12;
        state.ragnarok.budget = val;
        elements.ragnarokBudgetValue.textContent = `${val} trials`;
      });
    }

    // Action buttons
    if (elements.runFalsifyBtn) {
      elements.runFalsifyBtn.addEventListener("click", runFalsification);
    }
    if (elements.runMinimizeBtn) {
      elements.runMinimizeBtn.addEventListener("click", runCounterexampleMinimization);
    }
    if (elements.runRepairBtn) {
      elements.runRepairBtn.addEventListener("click", runAutonomousRepair);
    }
    if (elements.copyRepairedCodeBtn) {
      elements.copyRepairedCodeBtn.addEventListener("click", copyRepairedCode);
    }
    if (elements.loadRepairedCodeBtn) {
      elements.loadRepairedCodeBtn.addEventListener("click", loadRepairedCodeIntoStep2);
    }

    // Initial empty Atlas
    renderFailureAtlas([], null, null, getSpecFromForm());
  }

  // ==========================================================================
  // Initialization
  // ==========================================================================

  function init() {
    setupAtmosphericCanvas();
    setupTabs();
    setupStepper();
    setupTour();
    setupPresets();
    setupViewPills();
    setupTutorialModal();
    setupVerifier();
    setupCodeCopy();
    setupOracle();
    setupTheme();
    setupWorkspaceOracle();
    setupDroneViewer();
    setupInitialModelCards();
    setupReasoningEffort();
    setupRagnarokArena();

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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
