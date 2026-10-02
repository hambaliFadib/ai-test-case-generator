/* AI Test Case Generator — Workbench UI logic (v1.3.1)
   Vanilla JS. No frameworks. Truthful generation states only. */
(() => {
  "use strict";

  /* ── Helpers ─────────────────────────────────────────────────── */
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
    }[ch]));
  }

  const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const scrollBehavior = () => (reduceMotion() ? "auto" : "smooth");
  const isDrawerViewport = () => window.matchMedia("(max-width: 1023px)").matches;

  // Restart a CSS animation by re-adding its class after a reflow.
  function replayAnimation(el, className) {
    el.classList.remove(className);
    void el.offsetWidth;
    el.classList.add(className);
  }

  const PRIORITY_RANK = { high: 0, medium: 1, low: 2 };

  /* ── Elements ────────────────────────────────────────────────── */
  const themeToggle = $("#theme-toggle");
  const versionEl = $("#version-badge");
  const textInput = $("#requirement-text");
  const fileInput = $("#file-input");
  const fileNameEl = $("#file-name");
  const dropzone = $("#dropzone");
  const textTab = $("#text-tab");
  const fileTab = $("#file-tab");
  const textPanel = $("#text-panel");
  const filePanel = $("#file-panel");
  const profileSelect = $("#profile");
  const outputLanguageSelect = $("#outputLanguage");
  const runtimeProvider = $("#runtime-provider");
  const runtimeModel = $("#runtime-model");
  const generateButton = $("#generate-button");
  const generatingBlock = $("#generating-block");
  const generatingTimer = $("#generating-timer");
  const composePanel = $("#compose");
  const composeError = $("#compose-error");
  const composeSummary = $("#compose-summary");
  const summarySource = $("#summary-source");
  const summaryProfile = $("#summary-profile");
  const summaryLanguage = $("#summary-language");
  const editInputButton = $("#edit-input-button");
  const workbench = $("#workbench");
  const statusChip = $("#status-chip");
  const metricsEl = $("#metrics");
  const coveragePct = $("#coverage-pct");
  const coverageFill = $("#coverage-fill");
  const secondaryMetrics = $("#secondary-metrics");
  const evidenceDetails = $("#evidence-details");
  const evidenceMissing = $("#evidence-missing");
  const evidenceUnexpected = $("#evidence-unexpected");
  const evidenceDuplicates = $("#evidence-duplicates");
  const evidenceExcluded = $("#evidence-excluded");
  const diagnosticsDetails = $("#diagnostics-details");
  const diagnosticsBody = $("#diagnostics-body");
  const searchInput = $("#filter-search");
  const categorySelect = $("#filter-category");
  const prioritySelect = $("#filter-priority");
  const techniqueSelect = $("#filter-technique");
  const shownCount = $("#shown-count");
  const csvMessage = $("#csv-message");
  const downloadButton = $("#download-button");
  const resultsBody = $("#results-body");
  const inspector = $("#inspector");
  const inspectorScrim = $("#inspector-scrim");
  const inspectorClose = $("#inspector-close");
  const inspectorBody = $("#inspector-body");
  const inspectorTitle = $("#inspector-title");

  /* ── State ───────────────────────────────────────────────────── */
  const state = {
    mode: "text",
    run: null,             // last GenerationResult payload (or failed payload with cases)
    cases: [],             // cases from last run
    view: [],              // filtered + sorted view
    sort: { key: null, dir: "asc" },
    activeIndex: -1,        // index into state.view for roving tabindex
    selectedId: null,      // selected case id
    lastFocusedRow: null,  // for drawer focus return
    timerId: null,
    timerStartedAt: 0,
  };

  /* ── Theme ───────────────────────────────────────────────────── */
  const themePreferenceKey = "theme-preference";
  const systemTheme = () => (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

  function applyTheme(theme, persist = false) {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = theme;
    themeToggle.title = `Switch to ${next} mode`;
    themeToggle.setAttribute("aria-label", `Switch to ${next} mode`);
    themeToggle.setAttribute("aria-pressed", String(theme === "dark"));
    if (persist) localStorage.setItem(themePreferenceKey, theme);
  }

  const savedTheme = localStorage.getItem(themePreferenceKey);
  applyTheme(savedTheme === "dark" || savedTheme === "light" ? savedTheme : systemTheme());
  themeToggle.addEventListener("click", () => {
    applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark", true);
  });

  /* ── Compose mode (text / file) ──────────────────────────────── */
  function setMode(mode) {
    state.mode = mode;
    const textMode = mode === "text";
    textTab.setAttribute("aria-selected", String(textMode));
    fileTab.setAttribute("aria-selected", String(!textMode));
    textPanel.hidden = !textMode;
    filePanel.hidden = textMode;
  }
  textTab.addEventListener("click", () => setMode("text"));
  fileTab.addEventListener("click", () => setMode("file"));

  /* ── File handling ───────────────────────────────────────────── */
  function setFile(file) {
    if (!file) return;
    const allowed = [".docx", ".pdf", ".md"];
    const suffix = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!allowed.includes(suffix)) {
      showComposeError("Choose a .docx, .pdf, or .md file.");
      fileInput.value = "";
      fileNameEl.textContent = "";
      return;
    }
    fileInput.files = (() => {
      const transfer = new DataTransfer();
      transfer.items.add(file);
      return transfer.files;
    })();
    fileNameEl.textContent = file.name;
    showComposeError("");
  }

  $("#file-button").addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => setFile(fileInput.files[0]));
  ["dragenter", "dragover"].forEach((name) => dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    dropzone.classList.add("is-over");
  }));
  ["dragleave", "drop"].forEach((name) => dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    dropzone.classList.remove("is-over");
  }));
  dropzone.addEventListener("drop", (event) => setFile(event.dataTransfer.files[0]));

  /* ── Messages ────────────────────────────────────────────────── */
  function showComposeError(message) {
    composeError.textContent = message;
    composeError.hidden = !message;
  }

  function showCsvMessage(kind, message) {
    csvMessage.textContent = message;
    csvMessage.className = `message ${kind}`;
    csvMessage.hidden = !message;
    if (message && kind === "error") csvMessage.setAttribute("role", "alert");
    else csvMessage.removeAttribute("role");
  }

  /* ── Runtime config (read-only display) ──────────────────────── */
  let serverProvider = "openai";
  let serverModel = "mimo-v2.5";

  fetch("/api/config")
    .then((response) => (response.ok ? response.json() : null))
    .then((config) => {
      if (!config) return;
      serverProvider = config.provider || serverProvider;
      serverModel = config.model || serverModel;
      runtimeProvider.textContent = serverProvider;
      runtimeModel.textContent = serverModel;
    })
    .catch(() => {}); // silent fallback: defaults above remain

  /* ── Generation ──────────────────────────────────────────────── */
  function startTimer() {
    state.timerStartedAt = Date.now();
    generatingTimer.textContent = "0:00 elapsed";
    state.timerId = window.setInterval(() => {
      const seconds = Math.floor((Date.now() - state.timerStartedAt) / 1000);
      const m = Math.floor(seconds / 60);
      const s = String(seconds % 60).padStart(2, "0");
      generatingTimer.textContent = `${m}:${s} elapsed`;
    }, 1000);
  }

  function stopTimer() {
    if (state.timerId !== null) {
      window.clearInterval(state.timerId);
      state.timerId = null;
    }
  }

  function setGenerating(active) {
    generateButton.disabled = active;
    generatingBlock.hidden = !active;
    composePanel.setAttribute("aria-busy", String(active));
    if (state.run) workbench.setAttribute("aria-busy", String(active));
    if (active) startTimer();
    else stopTimer();
  }

  async function readError(response) {
    try {
      const body = await response.json();
      return body.detail || body.error || `Request failed (${response.status})`;
    } catch (_) {
      return `Request failed (${response.status})`;
    }
  }

  async function generate() {
    showComposeError("");
    showCsvMessage("", "");

    // Client validation (distinct from server errors)
    if (state.mode === "text" && !textInput.value.trim()) {
      showComposeError("Enter requirement text first.");
      textInput.focus();
      return;
    }
    if (state.mode === "file" && !fileInput.files[0]) {
      showComposeError("Choose a requirement file first.");
      $("#file-button").focus();
      return;
    }

    setGenerating(true);
    try {
      let response;
      const outputLanguage = outputLanguageSelect.value;
      if (state.mode === "text") {
        response = await fetch("/api/generate/text", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            text: textInput.value,
            provider: serverProvider,
            model: serverModel,
            language: "manual",
            output_language: outputLanguage,
            profile: profileSelect.value,
          }),
        });
      } else {
        const form = new FormData();
        form.append("file", fileInput.files[0]);
        form.append("provider", serverProvider);
        form.append("model", serverModel);
        form.append("language", "manual");
        form.append("output_language", outputLanguage);
        form.append("profile", profileSelect.value);
        response = await fetch("/api/generate/file", { method: "POST", body: form });
      }

      let payload = null;
      try { payload = await response.json(); } catch (_) { payload = null; }
      const usableCases = payload && Array.isArray(payload.test_cases) ? payload.test_cases : [];

      if (!response.ok) {
        const detail = (payload && (payload.detail || payload.error)) || `Request failed (${response.status})`;
        if (usableCases.length) {
          // Preserve and render usable cases from a failed response payload.
          renderRun(payload, { forcedError: detail });
        } else {
          showComposeError(detail);
        }
        return;
      }
      if (!payload || typeof payload !== "object") {
        showComposeError("The server returned an unexpected response.");
        return;
      }
      renderRun(payload);
    } catch (error) {
      showComposeError(error.message || "Generation failed. Check your connection and try again.");
    } finally {
      setGenerating(false);
    }
  }

  generateButton.addEventListener("click", generate);

  /* ── Compose collapse ────────────────────────────────────────── */
  function collapseCompose() {
    const source = state.mode === "text"
      ? `Paste text · ${textInput.value.trim().length.toLocaleString()} chars`
      : `File · ${fileInput.files[0] ? fileInput.files[0].name : "unknown"}`;
    summarySource.textContent = source;
    summaryProfile.textContent = profileSelect.options[profileSelect.selectedIndex].text;
    summaryLanguage.textContent = outputLanguageSelect.options[outputLanguageSelect.selectedIndex].text;
    composePanel.hidden = true;
    composeSummary.hidden = false;
  }

  editInputButton.addEventListener("click", () => {
    composeSummary.hidden = true;
    composePanel.hidden = false;
    (state.mode === "text" ? textInput : $("#file-button")).focus();
  });

  /* ── Result rendering ────────────────────────────────────────── */
  function statusLabel(status) {
    if (status === "complete") return "Complete";
    if (status === "partial") return "Partial";
    return "Failed";
  }

  function statusIconNode(status) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    if (status === "complete") path.setAttribute("d", "M3 8.5 6.5 12 13 4.5");
    else if (status === "partial") path.setAttribute("d", "M8 2v8");
    else path.setAttribute("d", "M4 4l8 8M12 4l-8 8");
    svg.append(path);
    return svg;
  }

  function coverageLevel(pct) {
    if (pct >= 100) return "full";
    if (pct > 0) return "some";
    return "none";
  }

  function metricNode(label, value) {
    const wrap = document.createElement("div");
    wrap.className = "metric";
    const lab = document.createElement("span");
    lab.className = "detail-label";
    lab.textContent = label;
    const val = document.createElement("span");
    val.className = "metric-value tnum";
    val.textContent = value;
    wrap.append(lab, val);
    return wrap;
  }

  function listEvidence(container, items, emptyNote) {
    container.replaceChildren();
    if (!items.length) {
      const p = document.createElement("p");
      p.className = "empty-note";
      p.textContent = emptyNote;
      container.append(p);
      return;
    }
    const ul = document.createElement("ul");
    items.forEach((item) => {
      const li = document.createElement("li");
      li.textContent = item;
      ul.append(li);
    });
    container.append(ul);
  }

  function renderRun(payload, options = {}) {
    const status = String(payload.status || "failed").toLowerCase();
    const cases = Array.isArray(payload.test_cases) ? payload.test_cases : [];
    state.run = payload;
    state.cases = cases;
    state.selectedId = null;
    state.activeIndex = cases.length ? 0 : -1;
    state.sort = { key: null, dir: "asc" };

    // Status chip
    statusChip.className = `chip chip-${status === "complete" ? "complete" : status === "partial" ? "partial" : "failed"}`;
    statusChip.replaceChildren(
      statusIconNode(status),
      Object.assign(document.createElement("span"), {
        textContent: options.forcedError ? "Failed (with cases)" : statusLabel(status),
      }),
    );
    replayAnimation(statusChip, "is-refreshing");

    // Metrics
    const pct = Number(payload.coverage_percentage || 0);
    const missing = Array.isArray(payload.missing_scenarios) ? payload.missing_scenarios : [];
    metricsEl.replaceChildren(
      metricNode("Coverage", `${pct.toFixed(2)}%`),
      metricNode("Scenarios planned", String(payload.scenario_count ?? 0)),
      metricNode("Cases generated", String(payload.generated_count ?? cases.length)),
      metricNode("Missing", String(missing.length)),
      metricNode("Excluded reqs", String(payload.excluded_requirement_count ?? 0)),
    );
    replayAnimation(metricsEl, "is-refreshing");

    coveragePct.textContent = `${pct.toFixed(2)}%`;
    coverageFill.style.setProperty("--pct", String(Math.min(1, Math.max(0, pct / 100))));
    coverageFill.dataset.level = coverageLevel(pct);
    // Color is not the only indicator: level text accompanies the bar.
    coverageFill.setAttribute("aria-hidden", "true");

    secondaryMetrics.textContent = [
      `${payload.requirement_count ?? 0} requirements parsed`,
      `${payload.testable_requirement_count ?? 0} testable`,
      `${payload.initial_generated_count ?? cases.length} initial cases`,
      `${payload.batch_count ?? 0} batches`,
      `${payload.backfill_count ?? 0} backfill calls`,
    ].join(" · ");

    // Evidence (secondary, collapsed)
    listEvidence(evidenceMissing, missing, "None — full planned coverage.");
    listEvidence(evidenceUnexpected, Array.isArray(payload.unexpected_scenarios) ? payload.unexpected_scenarios : [], "None.");
    listEvidence(evidenceDuplicates, Array.isArray(payload.duplicate_scenarios) ? payload.duplicate_scenarios : [], "None.");
    evidenceExcluded.textContent = String(payload.excluded_requirement_count ?? 0);
    const diagnostics = Array.isArray(payload.diagnostics) ? payload.diagnostics : [];
    diagnosticsDetails.hidden = diagnostics.length === 0;
    diagnosticsBody.textContent = diagnostics.length ? diagnostics.join("\n") : "";

    // Filters
    populateFilters(cases);

    // Forced error banner in workbench for failed-with-cases payloads
    if (options.forcedError) {
      showComposeError(options.forcedError);
    }

    // Table + inspector
    rebuildView();
    renderInspector(null);

    workbench.hidden = false;
    collapseCompose();
    workbench.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
  }

  /* ── Filters + sort ──────────────────────────────────────────── */
  function uniqueSorted(values) {
    return [...new Set(values.filter((v) => v !== undefined && v !== null && v !== ""))].sort((a, b) => String(a).localeCompare(String(b)));
  }

  function fillSelect(select, values, allLabel) {
    const current = select.value;
    select.replaceChildren();
    const all = document.createElement("option");
    all.value = "";
    all.textContent = allLabel;
    select.append(all);
    values.forEach((value) => {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = value;
      select.append(opt);
    });
    if ([...select.options].some((o) => o.value === current)) select.value = current;
  }

  function populateFilters(cases) {
    fillSelect(categorySelect, uniqueSorted(cases.map((c) => c.category)), "All categories");
    fillSelect(prioritySelect, ["high", "medium", "low"].filter((p) => cases.some((c) => c.priority === p)), "All priorities");
    fillSelect(techniqueSelect, uniqueSorted(cases.map((c) => c.technique)), "All techniques");
  }

  function matchesSearch(testCase, needle) {
    if (!needle) return true;
    const haystack = [testCase.id, testCase.title, testCase.requirement_ref, testCase.scenario_ref, testCase.technique]
      .join(" ").toLowerCase();
    return haystack.includes(needle);
  }

  function compareBy(key, a, b) {
    if (key === "priority") {
      return (PRIORITY_RANK[a.priority] ?? 9) - (PRIORITY_RANK[b.priority] ?? 9);
    }
    if (key === "trace") {
      return String(a.requirement_ref).localeCompare(String(b.requirement_ref))
        || String(a.scenario_ref).localeCompare(String(b.scenario_ref));
    }
    return String(a[key] ?? "").localeCompare(String(b[key] ?? ""), undefined, { numeric: true });
  }

  function rebuildView() {
    const needle = searchInput.value.trim().toLowerCase();
    const category = categorySelect.value;
    const priority = prioritySelect.value;
    const technique = techniqueSelect.value;

    let view = state.cases.filter((c) =>
      matchesSearch(c, needle)
      && (!category || c.category === category)
      && (!priority || c.priority === priority)
      && (!technique || c.technique === technique));

    if (state.sort.key) {
      const { key, dir } = state.sort;
      view = [...view].sort((a, b) => (dir === "asc" ? 1 : -1) * compareBy(key, a, b));
    }
    state.view = view;

    // Keep selection if still visible
    if (state.selectedId && !view.some((c) => c.id === state.selectedId)) {
      state.selectedId = null;
      renderInspector(null);
    }
    if (state.activeIndex >= view.length) state.activeIndex = view.length - 1;
    if (state.activeIndex < 0 && view.length) state.activeIndex = 0;

    renderTable();
    shownCount.textContent = `Showing ${view.length} of ${state.cases.length} cases`;
  }

  function renderTable() {
    resultsBody.replaceChildren();
    if (!state.view.length) {
      const tr = document.createElement("tr");
      tr.className = "is-static empty-row";
      const td = document.createElement("td");
      td.colSpan = 6;
      td.textContent = state.cases.length
        ? "No cases match the current search or filters."
        : "No test cases were returned.";
      tr.append(td);
      resultsBody.append(tr);
      return;
    }

    state.view.forEach((testCase, index) => {
      const tr = document.createElement("tr");
      tr.dataset.id = testCase.id;
      tr.tabIndex = index === state.activeIndex ? 0 : -1;
      if (testCase.id === state.selectedId) tr.setAttribute("aria-current", "true");

      const idTd = document.createElement("td");
      idTd.className = "cell-id";
      idTd.textContent = testCase.id;

      const titleTd = document.createElement("td");
      titleTd.className = "cell-title";
      titleTd.textContent = testCase.title;

      const catTd = document.createElement("td");
      const badge = document.createElement("span");
      badge.className = `badge badge-${escapeHtml(testCase.category)}`;
      badge.textContent = testCase.category;
      catTd.append(badge);

      const priTd = document.createElement("td");
      priTd.className = `priority priority-${escapeHtml(testCase.priority)}`;
      priTd.textContent = testCase.priority;

      const techTd = document.createElement("td");
      techTd.className = "technique";
      techTd.textContent = testCase.technique || "—";

      const traceTd = document.createElement("td");
      traceTd.className = "cell-trace";
      traceTd.title = `${testCase.requirement_ref} → ${testCase.scenario_ref}`;
      const reqSpan = document.createElement("span");
      reqSpan.textContent = testCase.requirement_ref;
      const arrow = document.createElement("span");
      arrow.className = "trace-arrow";
      arrow.textContent = "→";
      arrow.setAttribute("aria-hidden", "true");
      const scnSpan = document.createElement("span");
      scnSpan.className = "trace-scenario";
      scnSpan.textContent = testCase.scenario_ref;
      traceTd.append(reqSpan, arrow, scnSpan);

      tr.append(idTd, titleTd, catTd, priTd, techTd, traceTd);
      resultsBody.append(tr);
    });
  }

  [searchInput, categorySelect, prioritySelect, techniqueSelect].forEach((el) => {
    el.addEventListener("input", rebuildView);
    el.addEventListener("change", rebuildView);
  });

  // Sorting via header buttons
  $$(".th-sort").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.sort;
      const th = button.closest("th");
      const currently = th.getAttribute("aria-sort");
      const dir = currently === "ascending" ? "desc" : "asc";
      $$("thead th").forEach((h) => h.setAttribute("aria-sort", "none"));
      th.setAttribute("aria-sort", dir === "asc" ? "ascending" : "descending");
      state.sort = { key, dir: dir === "asc" ? "asc" : "desc" };
      rebuildView();
    });
  });

  /* ── Row interaction (roving tabindex, no grid role) ─────────── */
  function setActiveRow(index, { focus = true, select = false } = {}) {
    if (!state.view.length) return;
    const clamped = Math.max(0, Math.min(state.view.length - 1, index));
    state.activeIndex = clamped;
    const rows = $$("tr[data-id]", resultsBody);
    rows.forEach((row, i) => { row.tabIndex = i === clamped ? 0 : -1; });
    const row = rows[clamped];
    if (!row) return;
    if (focus) row.focus({ preventScroll: false });
    if (select) selectCase(state.view[clamped], row);
  }

  function selectCase(testCase, rowEl) {
    state.selectedId = testCase.id;
    state.lastFocusedRow = rowEl || null;
    $$("tr[data-id]", resultsBody).forEach((row) => {
      if (row.dataset.id === testCase.id) row.setAttribute("aria-current", "true");
      else row.removeAttribute("aria-current");
    });
    renderInspector(testCase);
    if (isDrawerViewport()) openDrawer();
  }

  resultsBody.addEventListener("click", (event) => {
    const row = event.target.closest("tr[data-id]");
    if (!row) return;
    const index = state.view.findIndex((c) => c.id === row.dataset.id);
    if (index >= 0) setActiveRow(index, { focus: false, select: true });
  });

  resultsBody.addEventListener("keydown", (event) => {
    const row = event.target.closest("tr[data-id]");
    if (!row) return;
    const index = state.view.findIndex((c) => c.id === row.dataset.id);
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        setActiveRow(index + 1);
        break;
      case "ArrowUp":
        event.preventDefault();
        setActiveRow(index - 1);
        break;
      case "Home":
        event.preventDefault();
        setActiveRow(0);
        break;
      case "End":
        event.preventDefault();
        setActiveRow(state.view.length - 1);
        break;
      case "Enter":
      case " ":
        event.preventDefault();
        setActiveRow(index, { focus: true, select: true });
        break;
      default:
        break;
    }
  });

  /* ── Inspector ───────────────────────────────────────────────── */
  function inspSection(label, contentNode) {
    const section = document.createElement("div");
    section.className = "insp-section";
    const lab = document.createElement("div");
    lab.className = "detail-label";
    lab.textContent = label;
    section.append(lab, contentNode);
    return section;
  }

  function factNode(label, value, { mono = false } = {}) {
    const fact = document.createElement("div");
    fact.className = "fact";
    const lab = document.createElement("span");
    lab.className = "detail-label";
    lab.textContent = label;
    const val = document.createElement("span");
    val.className = `fact-value${mono ? " mono-ref" : ""}`;
    val.textContent = value;
    fact.append(lab, val);
    return fact;
  }

  function renderInspector(testCase) {
    inspectorBody.replaceChildren();
    if (!testCase) {
      const p = document.createElement("p");
      p.className = "inspector-empty";
      p.textContent = "Select a row to inspect preconditions, steps, and expected result.";
      inspectorBody.append(p);
      inspectorTitle.textContent = "Test case";
      inspector.setAttribute("aria-labelledby", "inspector-title");
      replayAnimation(inspectorBody, "is-refreshing");
      return;
    }

    inspectorTitle.textContent = "Test case inspector";

    const title = document.createElement("h4");
    title.className = "inspector-title";
    title.id = "inspector-case-title";
    title.textContent = testCase.title;
    inspectorBody.append(title);
    inspector.setAttribute("aria-labelledby", "inspector-case-title");

    // Meta grid: category / priority / technique / language
    const meta = document.createElement("div");
    meta.className = "insp-meta";
    const catFact = factNode("Category", testCase.category);
    catFact.querySelector(".fact-value").className = `badge badge-${escapeHtml(testCase.category)}`;
    meta.append(
      catFact,
      factNode("Priority", testCase.priority),
      factNode("Technique", testCase.technique || "—"),
      factNode("Language target", testCase.language_target || "manual"),
    );
    inspectorBody.append(meta);

    // Preconditions
    const pre = document.createElement("ol");
    (testCase.preconditions || []).forEach((item) => {
      const li = document.createElement("li");
      li.textContent = item;
      pre.append(li);
    });
    if (!pre.children.length) {
      const p = document.createElement("p");
      p.textContent = "None specified.";
      inspectorBody.append(inspSection("Preconditions", p));
    } else {
      inspectorBody.append(inspSection("Preconditions", pre));
    }

    // Steps (ordered)
    const steps = document.createElement("ol");
    (testCase.steps || []).forEach((item) => {
      const li = document.createElement("li");
      li.textContent = item;
      steps.append(li);
    });
    inspectorBody.append(inspSection("Steps", steps));

    // Expected result
    const expected = document.createElement("p");
    expected.textContent = testCase.expected_result || "";
    inspectorBody.append(inspSection("Expected result", expected));

    // Traceability / meta
    const trace = document.createElement("div");
    trace.className = "insp-trace-grid";
    trace.append(
      factNode("Requirement ref", testCase.requirement_ref || "—", { mono: true }),
      factNode("Scenario ref", testCase.scenario_ref || "—", { mono: true }),
      factNode("Case ID", testCase.id, { mono: true }),
      factNode("Generated", testCase.generated_at || "—", { mono: true }),
    );
    inspectorBody.append(inspSection("Traceability", trace));
    replayAnimation(inspectorBody, "is-refreshing");
  }

  /* Drawer behavior (<1024px): dialog semantics + focus trap + focus return.
     Exit runs a short CSS leg; teardown and focus return happen when it ends. */
  let drawerReturnFocus = null;
  let drawerClosing = false;
  let drawerCloseTimer = null;

  function openDrawer() {
    if (!isDrawerViewport()) return;
    if (drawerCloseTimer !== null) {
      window.clearTimeout(drawerCloseTimer);
      drawerCloseTimer = null;
    }
    drawerClosing = false;
    inspector.classList.remove("is-closing");
    inspectorScrim.classList.remove("is-closing");
    drawerReturnFocus = state.lastFocusedRow || document.activeElement;
    inspector.classList.add("is-drawer", "is-open");
    inspector.setAttribute("role", "dialog");
    inspector.setAttribute("aria-modal", "true");
    inspectorScrim.classList.add("is-open");
    inspectorClose.focus();
  }

  function teardownDrawer() {
    drawerClosing = false;
    drawerCloseTimer = null;
    inspector.classList.remove("is-drawer", "is-open", "is-closing");
    inspector.removeAttribute("role");
    inspector.removeAttribute("aria-modal");
    inspectorScrim.classList.remove("is-open", "is-closing");
    state.selectedId = null;
    $$("tr[data-id]", resultsBody).forEach((row) => row.removeAttribute("aria-current"));
    if (drawerReturnFocus && document.contains(drawerReturnFocus)) drawerReturnFocus.focus();
    else {
      const row = $(`tr[data-id]`, resultsBody);
      if (row) row.focus();
    }
  }

  function closeDrawer() {
    if (!inspector.classList.contains("is-drawer") || drawerClosing) return;
    if (reduceMotion()) {
      teardownDrawer();
      return;
    }
    drawerClosing = true;
    inspector.classList.add("is-closing");
    inspectorScrim.classList.add("is-closing");
    drawerCloseTimer = window.setTimeout(teardownDrawer, 150);
  }

  inspectorClose.addEventListener("click", closeDrawer);
  inspectorScrim.addEventListener("click", closeDrawer);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && inspector.classList.contains("is-drawer")) {
      event.preventDefault();
      closeDrawer();
      return;
    }
    // Simple focus trap while drawer is open
    if (event.key === "Tab" && inspector.classList.contains("is-drawer")) {
      const focusables = $$('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])', inspector)
        .filter((el) => !el.disabled && el.offsetParent !== null);
      if (!focusables.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (!inspector.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      }
    }
  });

  window.addEventListener("resize", () => {
    if (!isDrawerViewport() && inspector.classList.contains("is-drawer")) {
      // Crossing into desktop: convert drawer back to persistent panel.
      if (drawerCloseTimer !== null) {
        window.clearTimeout(drawerCloseTimer);
        drawerCloseTimer = null;
      }
      drawerClosing = false;
      inspector.classList.remove("is-drawer", "is-open", "is-closing");
      inspector.removeAttribute("role");
      inspector.removeAttribute("aria-modal");
      inspectorScrim.classList.remove("is-open", "is-closing");
    }
  });

  /* ── CSV download ────────────────────────────────────────────── */
  downloadButton.addEventListener("click", async () => {
    if (!state.cases.length) return;
    downloadButton.disabled = true;
    showCsvMessage("", "");
    try {
      const response = await fetch("/api/export/csv", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ test_cases: state.cases, filename: "test_cases" }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `test_cases_${new Date().toISOString().slice(0, 10).replaceAll("-", "")}.csv`;
      link.click();
      URL.revokeObjectURL(url);
      showCsvMessage("success", `CSV downloaded · ${state.cases.length} cases.`);
    } catch (error) {
      showCsvMessage("error", `CSV download failed: ${error.message}`);
    } finally {
      downloadButton.disabled = false;
    }
  });

  /* ── Init ────────────────────────────────────────────────────── */
  if (versionEl) versionEl.textContent = "v1.3.1";
  setMode("text");
  renderInspector(null);
})();
