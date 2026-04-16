/**
 * PrintGrid — Frontend Logic
 * Upload, grid preview with tabs, processing, and download.
 */
(function () {
    "use strict";

    // --- DOM ---
    const uploadZone = document.getElementById("uploadZone");
    const fileInput = document.getElementById("fileInput");
    const fileInfo = document.getElementById("fileInfo");
    const fileName = document.getElementById("fileName");
    const removeFile = document.getElementById("removeFile");
    const gridRows = document.getElementById("gridRows");
    const gridCols = document.getElementById("gridCols");
    const paperSize = document.getElementById("paperSize");
    const marginInput = document.getElementById("margin");
    const previewFront = document.getElementById("previewFront");
    const previewBack = document.getElementById("previewBack");
    const previewCaption = document.getElementById("previewCaption");
    const infoSlots = document.getElementById("infoSlots");
    const infoPagesPerSheet = document.getElementById("infoPagesPerSheet");
    const processBtn = document.getElementById("processBtn");
    const progressContainer = document.getElementById("progressContainer");
    const progressFill = document.getElementById("progressFill");
    const progressText = document.getElementById("progressText");
    const resultSection = document.getElementById("resultSection");
    const resultSheets = document.getElementById("resultSheets");
    const resultPages = document.getElementById("resultPages");
    const downloadBtn = document.getElementById("downloadBtn");

    let selectedFile = null;
    let activeSide = "front";

    // --- Upload ---
    uploadZone.addEventListener("click", () => fileInput.click());

    uploadZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        uploadZone.classList.add("drag-over");
    });

    uploadZone.addEventListener("dragleave", () => {
        uploadZone.classList.remove("drag-over");
    });

    uploadZone.addEventListener("drop", (e) => {
        e.preventDefault();
        uploadZone.classList.remove("drag-over");
        const files = e.dataTransfer.files;
        if (files.length > 0 && files[0].type === "application/pdf") {
            setFile(files[0]);
        }
    });

    fileInput.addEventListener("change", () => {
        if (fileInput.files.length > 0) setFile(fileInput.files[0]);
    });

    removeFile.addEventListener("click", clearFile);

    function setFile(file) {
        selectedFile = file;
        const sizeMB = (file.size / 1024 / 1024).toFixed(2);
        fileName.textContent = `${file.name} (${sizeMB} MB)`;
        fileInfo.style.display = "flex";
        uploadZone.style.display = "none";
        processBtn.disabled = false;
        resultSection.style.display = "none";
    }

    function clearFile() {
        selectedFile = null;
        fileInput.value = "";
        fileInfo.style.display = "none";
        uploadZone.style.display = "";
        processBtn.disabled = true;
        resultSection.style.display = "none";
    }

    // --- Preview Tabs ---
    document.querySelectorAll(".preview-tab").forEach((tab) => {
        tab.addEventListener("click", () => {
            document.querySelectorAll(".preview-tab").forEach((t) => t.classList.remove("active"));
            tab.classList.add("active");
            activeSide = tab.dataset.side;

            previewFront.style.display = activeSide === "front" ? "" : "none";
            previewBack.style.display = activeSide === "back" ? "" : "none";
            previewCaption.textContent =
                activeSide === "back"
                    ? "Each row is reversed for short-edge duplex"
                    : "Pages arranged left-to-right, top-to-bottom";
        });
    });

    // --- Preview Grid ---
    function updatePreview() {
        const rows = parseInt(gridRows.value);
        const cols = parseInt(gridCols.value);
        const slots = rows * cols;

        previewFront.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
        previewBack.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;

        const frontPages = [];
        const backPages = [];
        for (let i = 0; i < slots; i++) {
            frontPages.push(i * 2 + 1);
            backPages.push(i * 2 + 2);
        }

        previewFront.innerHTML = frontPages
            .map((p) => `<div class="preview-cell">${p}</div>`)
            .join("");

        const backReversed = [];
        for (let r = 0; r < rows; r++) {
            const row = backPages.slice(r * cols, (r + 1) * cols);
            row.reverse();
            backReversed.push(...row);
        }

        previewBack.innerHTML = backReversed
            .map((p) => `<div class="preview-cell">${p}</div>`)
            .join("");

        // Info strip
        infoSlots.textContent = `${rows}\u00d7${cols} = ${slots} pages/side`;
        infoPagesPerSheet.textContent = `${slots * 2} pages/sheet`;
    }

    gridRows.addEventListener("change", updatePreview);
    gridCols.addEventListener("change", updatePreview);
    updatePreview();

    // --- Process ---
    processBtn.addEventListener("click", async () => {
        if (!selectedFile) return;

        processBtn.disabled = true;
        processBtn.closest(".card").classList.add("processing");
        progressContainer.style.display = "flex";
        resultSection.style.display = "none";
        progressFill.style.width = "10%";
        progressText.textContent = "Uploading...";

        const formData = new FormData();
        formData.append("pdf", selectedFile);
        formData.append("rows", gridRows.value);
        formData.append("cols", gridCols.value);
        formData.append("paper_size", paperSize.value);
        formData.append("margin", marginInput.value);

        try {
            progressFill.style.width = "40%";
            progressText.textContent = "Processing...";

            const response = await fetch("/api/process", {
                method: "POST",
                body: formData,
            });

            progressFill.style.width = "80%";
            const data = await response.json();

            if (!response.ok) throw new Error(data.error || "Processing failed");

            progressFill.style.width = "100%";
            progressText.textContent = "Done!";

            resultSheets.textContent = data.total_sheets;
            resultPages.textContent = data.output_pages;
            downloadBtn.href = data.download_url;
            resultSection.style.display = "block";

            setTimeout(() => {
                progressContainer.style.display = "none";
                processBtn.disabled = false;
                processBtn.closest(".card").classList.remove("processing");
            }, 800);
        } catch (err) {
            progressFill.style.width = "0%";
            progressText.textContent = `Error: ${err.message}`;
            processBtn.disabled = false;
            processBtn.closest(".card").classList.remove("processing");

            setTimeout(() => {
                progressContainer.style.display = "none";
            }, 4000);
        }
    });
})();
