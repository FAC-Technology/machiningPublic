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

function initialsFromRequestedBy() {
    const select = document.getElementById("id_requested_by");
    if (!select || !select.selectedOptions.length) return "";
    return select.selectedOptions[0].text.split("·")[0].trim();
}

function syncInitialsDestination() {
    const list = document.getElementById("destination-options");
    if (!list) return;
    const initials = initialsFromRequestedBy();
    let option = list.querySelector("option[data-initials='1']");
    if (!initials) {
        if (option) option.remove();
        return;
    }
    if (!option) {
        option = document.createElement("option");
        option.dataset.initials = "1";
        list.appendChild(option);
    }
    option.value = initials;
}

const requestedBy = document.getElementById("id_requested_by");
if (requestedBy) {
    requestedBy.addEventListener("change", syncInitialsDestination);
    syncInitialsDestination();
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

function selectPartNumberDigits(input) {
    const match = input.value.match(/^(PN-)(\d+)$/i);
    if (!match) return false;
    const start = match[1].length;
    input.setSelectionRange(start, input.value.length);
    return true;
}

const partNumber = document.getElementById("id_job_name");
if (partNumber) {
    partNumber.addEventListener("focus", () => {
        partNumber.dataset.selectDigits = "1";
        requestAnimationFrame(() => {
            if (partNumber.dataset.selectDigits === "1") selectPartNumberDigits(partNumber);
        });
    });
    partNumber.addEventListener("mouseup", (event) => {
        if (partNumber.dataset.selectDigits !== "1") return;
        if (selectPartNumberDigits(partNumber)) event.preventDefault();
        partNumber.dataset.selectDigits = "";
    });
    partNumber.addEventListener("blur", () => {
        partNumber.dataset.selectDigits = "";
    });
}
