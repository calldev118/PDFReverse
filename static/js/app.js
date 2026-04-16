/**
 * PDF Print Layout Tool — Frontend Logic
 * Handles file upload, grid preview, processing, and download.
 */
(function () {
    "use strict";

    // --- DOM Elements ---
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
    const processBtn = document.getElementById("processBtn");
    const progressContainer = document.getElementById("progressContainer");
    const progressFill = document.getElementById("progressFill");
    const progressText = document.getElementById("progressText");
    const resultSection = document.getElementById("resultSection");
    const resultSheets = document.getElementById("resultSheets");
    const resultPages = document.getElementById("resultPages");
    const downloadBtn = document.getElementById("downloadBtn");

    let selectedFile = null;

    // --- Upload Handling ---
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
        if (fileInput.files.length > 0) {
            setFile(fileInput.files[0]);
        }
    });

    removeFile.addEventListener("click", () => {
        clearFile();
    });

    function setFile(file) {
        selectedFile = file;
        fileName.textContent = `${file.name} (${(file.size / 1024 / 1024).toFixed(2)} MB)`;
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

    // --- Grid Preview ---
    function updatePreview() {
        const rows = parseInt(gridRows.value);
        const cols = parseInt(gridCols.value);
        const slotsPerSide = rows * cols;

        previewFront.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
        previewBack.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;

        // Build front pages: 1, 3, 5, 7... (odd positions)
        const frontPages = [];
        const backPages = [];
        for (let i = 0; i < slotsPerSide; i++) {
            frontPages.push(i * 2 + 1);
            backPages.push(i * 2 + 2);
        }

        // Build front grid HTML
        previewFront.innerHTML = frontPages
            .map((p) => `<div class="preview-cell">${p}</div>`)
            .join("");

        // Build back grid with row reversal
        const backReversed = [];
        for (let r = 0; r < rows; r++) {
            const row = backPages.slice(r * cols, (r + 1) * cols);
            row.reverse();
            backReversed.push(...row);
        }

        previewBack.innerHTML = backReversed
            .map((p) => `<div class="preview-cell">${p}</div>`)
            .join("");
    }

    gridRows.addEventListener("change", updatePreview);
    gridCols.addEventListener("change", updatePreview);

    // Initial preview
    updatePreview();

    // --- Process ---
    processBtn.addEventListener("click", async () => {
        if (!selectedFile) return;

        processBtn.disabled = true;
        progressContainer.style.display = "block";
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

            if (!response.ok) {
                throw new Error(data.error || "Processing failed");
            }

            progressFill.style.width = "100%";
            progressText.textContent = "Done!";

            // Show result
            resultSheets.textContent = data.total_sheets;
            resultPages.textContent = data.output_pages;
            downloadBtn.href = data.download_url;
            resultSection.style.display = "block";

            setTimeout(() => {
                progressContainer.style.display = "none";
                processBtn.disabled = false;
            }, 1000);
        } catch (err) {
            progressFill.style.width = "0%";
            progressText.textContent = `Error: ${err.message}`;
            processBtn.disabled = false;

            setTimeout(() => {
                progressContainer.style.display = "none";
            }, 4000);
        }
    });
})();
