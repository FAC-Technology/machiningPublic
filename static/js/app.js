const INPUTS = {
    pdf: "id_drawing_pdf",
    dxf: "id_drawing_dxf",
    vcarve: "id_vcarve_file",
};
const LABELS = { pdf: "PDF", dxf: "DXF", vcarve: "VCarve" };

function extensionOf(name) {
    const parts = name.toLowerCase().split(".");
    return parts.length > 1 ? `.${parts.pop()}` : "";
}

function kindOf(name) {
    const ext = extensionOf(name);
    if (ext === ".pdf") return "pdf";
    if (ext === ".dxf") return "dxf";
    if (ext === ".crv" || ext === ".crv3d") return "vcarve";
    return "other";
}

function setInputFile(id, file) {
    const input = document.getElementById(id);
    if (!input) return;
    const transfer = new DataTransfer();
    if (file) transfer.items.add(file);
    input.files = transfer.files;
}

function currentFile(kind) {
    const input = document.getElementById(INPUTS[kind]);
    return input && input.files[0] ? input.files[0] : null;
}

function updateStatus(messageText) {
    Object.keys(LABELS).forEach((kind) => {
        const row = document.querySelector(`[data-kind="${kind}"]`);
        if (!row) return;
        const file = currentFile(kind);
        const existing = !file && row.dataset.existing;
        if (file) {
            row.textContent = `${LABELS[kind]}: ${file.name}`;
            row.classList.add("is-ready");
            row.classList.remove("is-missing");
        } else if (existing) {
            row.textContent = `${LABELS[kind]}: ${existing}`;
            row.classList.add("is-ready");
            row.classList.remove("is-missing");
        } else {
            row.textContent = `${LABELS[kind]}: not added`;
            row.classList.remove("is-ready");
            row.classList.add("is-missing");
        }
    });
    const message = document.getElementById("drop-message");
    if (message && messageText) message.textContent = messageText;
}

function applyFiles(fileList, replaceAll) {
    const next = replaceAll
        ? { pdf: null, dxf: null, vcarve: null }
        : {
              pdf: currentFile("pdf"),
              dxf: currentFile("dxf"),
              vcarve: currentFile("vcarve"),
          };
    const ignored = [];
    Array.from(fileList || []).forEach((file) => {
        const kind = kindOf(file.name);
        if (kind === "other") ignored.push(file.name);
        else next[kind] = file;
    });
    setInputFile(INPUTS.pdf, next.pdf);
    setInputFile(INPUTS.dxf, next.dxf);
    setInputFile(INPUTS.vcarve, next.vcarve);
    const ready = Object.keys(LABELS).filter((kind) => next[kind] || document.querySelector(`[data-kind="${kind}"]`)?.dataset.existing);
    let message = `Attached: ${ready.length ? ready.map((kind) => LABELS[kind]).join(", ") : "none yet"}.`;
    if (ignored.length) {
        message += ` Ignored (wrong type): ${ignored.join(", ")}.`;
    }
    if (next.pdf && next.dxf && next.vcarve) {
        message = "All three file types are attached.";
    }
    updateStatus(message);
}

const dropZone = document.getElementById("drop-zone");
const picker = document.getElementById("file-picker");
const form = document.getElementById("job-form");

if (dropZone && picker) {
    document.querySelectorAll("#file-status [data-kind]").forEach((row) => {
        const text = row.textContent || "";
        const match = text.match(/: (.+)$/);
        if (match && match[1] !== "not added") row.dataset.existing = match[1];
    });
    dropZone.addEventListener("click", (event) => {
        if (event.target.closest("input")) return;
        picker.click();
    });
    dropZone.addEventListener("dragover", (event) => {
        event.preventDefault();
        dropZone.classList.add("is-hover");
    });
    dropZone.addEventListener("dragleave", () => dropZone.classList.remove("is-hover"));
    dropZone.addEventListener("drop", (event) => {
        event.preventDefault();
        dropZone.classList.remove("is-hover");
        applyFiles(event.dataTransfer.files, false);
    });
    picker.addEventListener("click", (event) => event.stopPropagation());
    picker.addEventListener("change", () => applyFiles(picker.files, false));
}

if (form) {
    form.addEventListener("submit", (event) => {
        const isEdit = form.dataset.editing === "1";
        const missing = Object.keys(LABELS).filter((kind) => {
            const row = document.querySelector(`[data-kind="${kind}"]`);
            return !currentFile(kind) && !(row && row.dataset.existing);
        });
        if (!isEdit && missing.length) {
            event.preventDefault();
            updateStatus(`Still needed: ${missing.map((kind) => LABELS[kind]).join(", ")}.`);
        }
    });
}

const THEME_KEY = "mq-theme";

function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
}

function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try {
        localStorage.setItem(THEME_KEY, theme);
    } catch (e) {}
    document.querySelectorAll(".theme-toggle [data-theme-value]").forEach((button) => {
        button.classList.toggle("is-active", button.dataset.themeValue === theme);
    });
}

applyTheme(currentTheme());
document.querySelectorAll(".theme-toggle [data-theme-value]").forEach((button) => {
    button.addEventListener("click", () => applyTheme(button.dataset.themeValue));
});

const PART_PREFIX = "PN-";
const PART_WIDTH = 5;

function partDigits(value) {
    return (value || "").replace(/^PN-/i, "").replace(/\D/g, "");
}

function formatPartNumber(digits) {
    return PART_PREFIX + (digits || "").slice(-PART_WIDTH).padStart(PART_WIDTH, "0");
}

function bindPartNumber(input) {
    if (!input) return;

    function apply(digits) {
        input.value = formatPartNumber(digits);
        const pos = input.value.length;
        input.setSelectionRange(pos, pos);
    }

    input.addEventListener("focus", () => {
        requestAnimationFrame(() => {
            const start = PART_PREFIX.length;
            input.setSelectionRange(start, input.value.length);
        });
    });

    input.addEventListener("keydown", (event) => {
        if (event.ctrlKey || event.metaKey || event.altKey) return;
        if (event.key >= "0" && event.key <= "9") {
            event.preventDefault();
            apply(partDigits(input.value) + event.key);
            return;
        }
        if (event.key === "Backspace" || event.key === "Delete") {
            event.preventDefault();
            apply(partDigits(input.value).slice(0, -1));
        }
    });

    input.addEventListener("paste", (event) => {
        event.preventDefault();
        const text = (event.clipboardData || window.clipboardData).getData("text");
        apply(partDigits(text));
    });

    input.addEventListener("blur", () => {
        apply(partDigits(input.value));
    });
}

bindPartNumber(document.getElementById("id_job_name"));

function bindRdProjectFields() {
    const form = document.getElementById("job-form");
    if (!form) return;
    const rdId = form.dataset.rdProjectId;
    const project = form.querySelector('[name="project"]');
    const partNumber = document.getElementById("part-number-field");
    const partVersion = document.getElementById("part-version-field");
    const rdName = document.getElementById("rd-name-field");
    if (!project || !partNumber || !partVersion || !rdName) return;

    function setDisabled(field, disabled) {
        field.querySelectorAll("input, select, textarea").forEach((el) => {
            el.disabled = disabled;
        });
    }

    function sync() {
        const isRd = Boolean(rdId) && project.value === rdId;
        partNumber.hidden = isRd;
        partVersion.hidden = isRd;
        rdName.hidden = !isRd;
        setDisabled(partNumber, isRd);
        setDisabled(partVersion, isRd);
        setDisabled(rdName, !isRd);
    }

    project.addEventListener("change", sync);
    sync();
}

bindRdProjectFields();

bindLetterInitials(document.getElementById("id_person-initials"));

function bindLetterInitials(input) {
    if (!input) return;
    input.addEventListener("input", () => {
        const next = input.value.replace(/[^A-Za-z]/g, "").slice(0, 4).toUpperCase();
        if (input.value === next) return;
        input.value = next;
        input.setSelectionRange(next.length, next.length);
    });
}

function bindMachinistChoice() {
    document.querySelectorAll(".js-machinist-choice").forEach((select) => {
        const otherRow = document.getElementById(select.dataset.otherRow);
        if (!otherRow) return;
        function sync() {
            otherRow.hidden = select.value !== "other";
        }
        select.addEventListener("change", sync);
        sync();
    });
}

bindMachinistChoice();

function bindAbandonDialog() {
    const dialog = document.getElementById("abandon-dialog");
    const open = document.getElementById("abandon-open");
    const cancel = document.getElementById("abandon-cancel");
    if (!dialog || !open) return;
    const reason = dialog.querySelector("[name=abandon_reason]");
    open.addEventListener("click", () => dialog.showModal());
    if (cancel) cancel.addEventListener("click", () => dialog.close());
    const confirm = dialog.querySelector("[value='abandon']");
    if (confirm && reason) {
        confirm.addEventListener("click", (event) => {
            if (!reason.value.trim()) {
                event.preventDefault();
                reason.focus();
            }
        });
    }
}

bindAbandonDialog();
