import os
import json
import pdfplumber
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent / "data"

def detect_scanned_pdf(pdf_path):
    """
    Opens the PDF and tries to read the first page.
    Returns True if text is missing or too short (likely a scan).
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                return True
            
            first_page_text = pdf.pages[0].extract_text()
            
            if not first_page_text or len(first_page_text.strip()) < 50:
                return True
            return False
    except Exception as e:
        print(f"Error reading {pdf_path.name}: {e}")
        return True

def generate_metadata(root_dir):
    count = 0
    scan_count = 0
    
    print(f"Scanning directory: {root_dir}")

    for pdf_path in root_dir.rglob("*.pdf"):
        
        relative_path = pdf_path.relative_to(root_dir)
        parts = relative_path.parts
        folder_depth = len(parts) - 1
        
        if folder_depth == 1:
            # Type A: Title 13 (Flat)
            title_group = parts[0]
            agency_name = parts[0]
        elif folder_depth >= 2:
            # Type B: Title 10 (Nested)
            title_group = parts[0]
            agency_name = parts[1]
        else:
            title_group = "Root"
            agency_name = "Unknown"

        is_scanned = detect_scanned_pdf(pdf_path)
        if is_scanned:
            scan_count += 1
            print(f"📷 Scanned/Image detected: {pdf_path.name}")

        # { "metadataAttributes": { "key": "value" } }
        metadata = {
            "metadataAttributes": {
                "agency": agency_name,
                "title": title_group,
                "filename": pdf_path.name,
                "is_scanned": str(is_scanned).lower()
            }
        }

        # If file is 'doc.pdf', meta file is 'doc.pdf.metadata.json'
        meta_filename = pdf_path.name + ".metadata.json"
        meta_path = pdf_path.parent / meta_filename
        
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
        
        count += 1
        if count % 10 == 0:
            print(f"Processed {count} files...")

    print("-" * 30)
    print(f"Complete! Processed {count} documents.")
    print(f"Found {scan_count} potentially scanned files.")

if __name__ == "__main__":
    if ROOT_DIR.exists():
        generate_metadata(ROOT_DIR)
    else:
        print(f"Error: Data directory not found at {ROOT_DIR}")