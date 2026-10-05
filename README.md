# SlideCraft — PDF to Editable PowerPoint Converter

A modern, high-fidelity web application that converts PDF documents into **100% editable Microsoft PowerPoint presentations (`.pptx`)**. Unlike traditional OCR converters that mangle fonts, misalign words, and produce messy floating text boxes, SlideCraft uses **Intelligent Visual Element Decomposition**:
- **Independent Picture Shapes**: Headers, title cards, diagrams, content columns, illustrations, badges, and citations are extracted as separate high-resolution picture shapes positioned at their exact original coordinates.
- **100% Visual Fidelity**: Mathematical formulas, chemical structures, custom brand fonts, and graphics retain their crisp, original look with zero OCR distortion.
- **Movable & Rearrangeable**: Every element can be selected, moved, resized, replaced, reordered, or deleted in Microsoft PowerPoint, Google Slides, Keynote, and LibreOffice Impress.
- **Clean Slide Background**: Detects and applies the slide's dominant background color behind the elements.
- **Gemini Vision Intelligence**: Leverages Google Gemini Vision to understand slide layout structure and identify semantic blocks with multi-model fallback.
- **Smart Algorithmic Fallback**: When offline or if an API key is not configured, automatic perimeter sampling and layout detection ensure dependable conversions.

---

## Features

1. **Independent Picture Elements**: Header banners, cards, diagrams, and illustrations are cropped into individual picture shapes you can move, resize, replace, or rearrange in PowerPoint.
2. **Zero OCR Formatting Loss**: Say goodbye to broken text blocks, bad line wrapping, and mismatched font replacements.
3. **Visual Slide Preview & Page Range Selection**: Render interactive thumbnails of your PDF pages before converting. Select/deselect specific pages or specify custom ranges (e.g. `1-3, 5, 8-10`).
4. **Batch Conversion**: Upload multiple PDF documents at once and convert them in parallel.
5. **Slide Aspect Ratio Controls**: Choose between `16:9 Widescreen` (default modern standard), `4:3 Standard`, or `Auto` (matches source PDF aspect ratio).
6. **Real-time Live Progress via SSE**: Server-Sent Events stream live status through the 4 pipeline stages (Render Slide → AI Element Segmentation → Build Slides → Ready).
7. **Sleek Modern UI**: Premium glassmorphic dark theme, responsive layout, and smooth micro-animations.

---

## Architecture

```
pdf-to-ppt/
├── backend/
│   ├── main.py                  # FastAPI server, SSE stream & REST endpoints
│   ├── config.py                # Environment and storage configuration
│   ├── requirements.txt         # Python library dependencies
│   ├── models/
│   │   └── schemas.py           # Pydantic models for extraction & tasks
│   └── services/
│       ├── pdf_extractor.py     # PyMuPDF text, styles & image extractor
│       ├── ai_analyzer.py       # Gemini 2.5 Flash layout analysis + fallback
│       ├── coordinate_mapper.py # PDF points to PPTX Inches / Pt conversion
│       ├── pptx_builder.py      # python-pptx native slide assembler
│       └── converter.py         # Asynchronous task orchestrator
├── frontend/
│   ├── index.html               # Main application interface
│   ├── css/
│   │   └── styles.css           # Glassmorphism dark design system
│   └── js/
│       ├── app.js               # Main application logic & event handlers
│       ├── preview.js           # Visual PDF page selector with thumbnails
│       └── progress.js          # Live SSE progress bar & status tracker
├── uploads/                     # Working directory for uploaded files
├── outputs/                     # Generated .pptx presentations
├── .env.example                 # Sample configuration
└── README.md
```

---

## Getting Started

### 1. Prerequisites
- Python 3.10+ (Tested with Python 3.14)
- (Optional) Google Gemini API Key (Get a free key at [Google AI Studio](https://aistudio.google.com/))

### 2. Setup Virtual Environment & Dependencies

```bash
# Create and activate virtual environment
python -m venv venv

# Windows PowerShell:
.\venv\Scripts\Activate.ps1

# Install requirements
pip install -r backend/requirements.txt
```

### 3. Configure Gemini API Key (Optional)

You can set your Gemini API key in two ways:
1. **Via `.env` file**:
   ```bash
   cp .env.example .env
   # Add your key to .env:
   # GEMINI_API_KEY=AIzaSy...
   ```
2. **Directly in the Web UI**: Click the **"AI Settings"** button in the top navigation bar and enter your key. It will be securely stored in your browser's local storage and used for conversions.

*Note: If no API key is provided, SlideCraft automatically uses its built-in rule-based layout analyzer.*

### 4. Run the Application

```bash
# Windows PowerShell:
.\venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Open your browser and navigate to:
**[http://127.0.0.1:8000](http://127.0.0.1:8000)**

---

## Conversion Pipeline

```
1. Extract (PyMuPDF)
   ├── Text blocks with font name, size, color, bold/italic, bounding boxes
   ├── High-res embedded images and raster positions
   └── Vector fill shapes, cards, and page dimensions
         ↓
2. Analyze (Gemini 2.5 / Algorithmic)
   ├── Identifies semantic roles (title, subtitle, heading, body, bullet, caption)
   └── Merges fragmented lines into unified multi-line paragraphs
         ↓
3. Map Coordinates (CoordinateMapper)
   ├── Translates PDF points to PowerPoint Inches / EMUs
   └── Scales font sizes and adds layout width buffers
         ↓
4. Build PPTX (python-pptx)
   ├── Creates editable TextBox shapes with formatting & word wrapping
   └── Inserts native Picture shapes and vector cards
```
