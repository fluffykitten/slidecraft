<div align="center">

# SlideCraft ⚡
### High-Fidelity PDF to Editable PowerPoint Presentation Converter

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Google Gemini](https://img.shields.io/badge/Gemini_Vision-AI_Powered-8E75C2?style=for-the-badge&logo=google&logoColor=white)](https://aistudio.google.com)
[![PowerPoint](https://img.shields.io/badge/Microsoft_PowerPoint-PPTX_Native-D04423?style=for-the-badge&logo=microsoftpowerpoint&logoColor=white)](https://products.office.com/powerpoint)
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](LICENSE)

*Transform locked PDFs into clean, beautiful, and fully editable PowerPoint presentations without mangled fonts, awkward line breaks, or lost illustrations.*

[Features](#-key-features) • [Quick Start](#-quick-start) • [Architecture](#-architecture--pipeline) • [Region Editor](#-interactive-slide-region-editor) • [API](#-api-endpoints) • [License](#-license)

</div>

---

## 💡 The Problem SlideCraft Solves

Traditional PDF-to-PowerPoint tools force an impossible compromise:
* **Generic OCR Converters** chop single sentences into multiple hard-wrapped lines, mangle complex headings, turn charts and chemical/mathematical formulas into unreadable garbage, and replace fonts with misaligned browser defaults.
* **Image Exporters** simply screenshot entire pages, leaving slides non-editable and useless for presentations.

**SlideCraft introduces a Hybrid Decomposition Engine**:
1. **Semantic Text & Typography Engine**: Continuous prose sentences stay intact as native paragraphs that reflow smoothly when edited in PowerPoint. Headings, body text, bullets, and badges retain their proportional sizing and formatting.
2. **Moveable Picture Elements**: Illustrations, icons, chemical bonds, and diagrams are cleanly cropped into high-resolution, transparent picture shapes placed at their exact slide coordinates.
3. **Interactive Region Inspector**: A built-in visual canvas lets you inspect, draw, resize, and reclassify custom regions (Text Box, Picture Shape, Data Table) for each slide before exporting.
4. **Native Table Reconstruction**: Data matrices and comparison grids are exported as true PowerPoint tables with theme styling and column alignments.

---

## ✨ Key Features

* **🎯 Interactive Region Editor**: Open any slide in a visual inspector. Draw custom bounding boxes with one click (`Text Box`, `Picture Shape`, `Data Table`), or click **Auto-Detect** to let Gemini Vision segment elements automatically.
* **📝 Semantic Paragraph Reflow**: No artificial line-breaks. Multi-line descriptions and card paragraphs reflow naturally when widened, edited, or restyled in Microsoft PowerPoint, Google Slides, Keynote, or LibreOffice.
* **📐 Typography-Accurate Font Fitting**: Mathematical bounding-box calculation simulates true word-wrapping, preventing font crushing and guaranteeing zero mid-word hyphenation.
* **🖼️ Clean Element Separation**: Diagrams, icons, and illustrations are cropped into standalone shapes you can move, resize, replace, or delete.
* **📊 Styled PowerPoint Tables**: Exports data tables with column alignments (left for text, right for numeric data) and custom header fills.
* **🏷️ Badge & Card Detection**: Automatically recognizes solid-fill cards and pills (e.g. status tags, warning cards), applying native PowerPoint rounded rectangle shapes and theme colors.
* **⚡ Live Real-Time Progress via SSE**: Server-Sent Events (SSE) stream live conversion progress across all pipeline stages with second-by-second feedback.
* **🎨 Minimalist Glassmorphic UI**: Ultra-clean, modern interface designed with native CSS, dark mode aesthetics, and zero unnecessary visual clutter.
* **🔒 Privacy-First**: Files are processed locally on your server. Documents are stored in temporary working folders and cleaned up automatically.

---

## 🚀 Quick Start

### 1. Prerequisites
* **Python 3.10+** (Tested on Python 3.10, 3.11, 3.12, 3.13, 3.14)
* *(Optional)* A free **Google Gemini API Key** from [Google AI Studio](https://aistudio.google.com/) for AI-powered vision segmentation and OCR.

### 2. Clone the Repository
```bash
git clone https://github.com/fluffykitten/slidecraft.git
cd slidecraft
```

### 3. Create a Virtual Environment & Install Dependencies
```bash
# Create virtual environment
python -m venv venv

# Activate (Windows PowerShell):
.\venv\Scripts\Activate.ps1

# Activate (macOS / Linux):
source venv/bin/activate

# Install requirements
pip install -r backend/requirements.txt
```

### 4. Configuration (Optional)
Copy the example environment file:
```bash
cp .env.example .env
```
Edit `.env` to configure your settings:
```env
# Optional: System-wide Gemini API Key (can also be entered directly in the web UI)
GEMINI_API_KEY=your_api_key_here

# Server settings
MAX_FILE_SIZE_MB=50
MAX_PAGES=100
MAX_CONCURRENT_TASKS=3
UPLOAD_DIR=./uploads
OUTPUT_DIR=./outputs
```

> **Note**: An API key is optional! If no Gemini API key is provided, SlideCraft operates seamlessly using its built-in rule-based layout analyzer.

### 5. Launch the Application
```bash
# Windows PowerShell:
.\venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload

# macOS / Linux:
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Open your browser and navigate to:
👉 **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

---

## 🎨 Interactive Slide Region Editor

When uploading a PDF, SlideCraft generates an interactive thumbnail preview of every slide:

1. **Inspect Any Slide**: Click the **"Select Regions"** button on any slide card.
2. **Auto-Detect AI Elements**: Click **"Auto-Detect"** to have Gemini analyze layout structure, separating text from illustrations and tables.
3. **Draw & Adjust Custom Regions**:
   * 🟦 **Text Box**: Draw over titles, card descriptions, or bullet lists to turn them into editable PowerPoint text with intelligent font sizing.
   * 🟩 **Picture Shape**: Draw over diagrams, formulas, logos, or illustrations to crop them into moveable vector-sharp pictures.
   * 🟪 **Data Table**: Draw over tables to export them as native editable PowerPoint tables.
4. **Drag, Resize, or Delete**: Adjust bounding boxes with precision handles.
5. **Save & Convert**: Hit **"Save Regions"**, and your custom layout blueprint is applied during conversion!

---

## 🏗️ Architecture & Pipeline

```
                              PDF Upload
                                  │
                                  ▼
                   ┌──────────────────────────────┐
                   │   PDF Rendering & Parsing    │
                   │         (PyMuPDF)            │
                   └──────────────┬───────────────┘
                                  │
                  ┌───────────────┴───────────────┐
                  ▼                               ▼
       User Custom Regions?               AI Decomposition
    (Region Inspector Canvas)          (Gemini Vision Engine)
                  │                               │
                  └───────────────┬───────────────┘
                                  │
                                  ▼
                   ┌──────────────────────────────┐
                   │    Structured OCR & Fit      │
                   │ • Physical Scale Calibration │
                   │ • Semantic Paragraph Reflow  │
                   │ • Container Pill & Card Fills│
                   │ • Table Alignment & Themes   │
                   └──────────────┬───────────────┘
                                  │
                                  ▼
                   ┌──────────────────────────────┐
                   │    Native PPTX Assembler     │
                   │        (python-pptx)         │
                   │ • Bounding Box Mapping       │
                   │ • <a:normAutofit/> XML Guard │
                   │ • Rounded Card Shapes        │
                   │ • Styled PowerPoint Tables   │
                   └──────────────┬───────────────┘
                                  │
                                  ▼
                         Editable .pptx Deck
```

---

## 📂 Project Structure

```
slidecraft/
├── backend/
│   ├── main.py                  # FastAPI application & REST endpoints
│   ├── config.py                # Environment configuration & limits
│   ├── requirements.txt         # Python dependencies
│   ├── models/
│   │   └── schemas.py           # Pydantic models (TextBlock, ExtractedTable, etc.)
│   └── services/
│       ├── ai_analyzer.py       # Gemini Vision decomposition & calibrated OCR
│       ├── converter.py         # Async task manager & background pipeline
│       ├── coordinate_mapper.py # PDF points to PPTX dimensions & DPI scaling
│       ├── pdf_extractor.py     # High-res PyMuPDF slide renderer
│       └── pptx_builder.py      # python-pptx presentation assembler
├── frontend/
│   ├── index.html               # Minimalist presentation interface
│   ├── css/
│   │   └── styles.css           # Modern design tokens & layout
│   └── js/
│       ├── app.js               # Application orchestration & API requests
│       ├── preview.js           # Slide thumbnail grid & page range selector
│       ├── progress.js          # Live SSE progress bar & status notifications
│       └── region_editor.js     # Interactive visual region inspector canvas
├── uploads/                     # Temporary storage for uploaded documents
├── outputs/                     # Generated presentation decks
├── .env.example                 # Example configuration template
└── README.md
```

---

## 🔌 API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/convert` | Starts background conversion. Accepts PDF file, conversion mode, slide ratio, and custom regions. |
| `GET` | `/api/tasks/{task_id}/progress` | Server-Sent Events (SSE) live progress stream. |
| `GET` | `/api/tasks/{task_id}/download` | Downloads the generated `.pptx` file. |
| `POST` | `/api/preview` | Generates thumbnail previews and metadata for all pages in a PDF. |
| `POST` | `/api/detect-slide-regions` | Runs Gemini Vision layout detection on a single slide for the Region Editor. |
| `POST` | `/api/validate-key` | Validates a user-supplied Gemini API key. |

---

## 🛠️ Technology Stack

* **Backend**: [FastAPI](https://fastapi.tiangolo.com/), [Uvicorn](https://www.uvicorn.org/), [Pydantic v2](https://docs.pydantic.dev/)
* **Document Processing**: [PyMuPDF (fitz)](https://pymupdf.readthedocs.io/), [Pillow (PIL)](https://python-pillow.org/)
* **Presentation Generation**: [python-pptx](https://python-pptx.readthedocs.io/)
* **AI Intelligence**: [Google GenAI SDK](https://github.com/google-gemini/generative-ai-python) (`gemini-3.5-flash-lite`, `gemini-2.5-flash`)
* **Frontend**: Vanilla JavaScript (ES6+), HTML5 Canvas, Modern CSS Custom Properties

---

## 🤝 Contributing

Contributions, feature requests, and bug reports are welcome!
1. Fork the Project.
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`).
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`).
4. Push to the Branch (`git push origin feature/AmazingFeature`).
5. Open a Pull Request.

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for more information.

<div align="center">
Made with ❤️ for clean, editable presentations.
</div>

