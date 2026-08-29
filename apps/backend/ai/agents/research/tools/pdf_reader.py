"""
apps/backend/ai/agents/research/tools/pdf_reader.py
PDF Document Parser for Academic Papers, Technical Specifications, and Industry Reports.
Extracts sections (Abstract, Methodology, Results, Limitations), tables, and citations.
"""
import io
import re
import os
import asyncio
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger("JARVIS.ResearchTools.PDFReader")


class ResearchPDFReader:
    """
    Parses PDF documents into structured sections and atomic evidence fragments.
    """

    @classmethod
    async def parse_pdf_file_or_bytes(
        cls,
        file_path_or_bytes: Any,
        max_pages: int = 25
    ) -> Dict[str, Any]:
        """
        Parses a PDF file from a path or raw bytes and extracts metadata and structured sections.
        """
        def _parse():
            text_by_page = []
            try:
                import pypdf
                reader = None
                if isinstance(file_path_or_bytes, (str, os.PathLike)):
                    if not os.path.exists(file_path_or_bytes):
                        return {"error": f"File not found: {file_path_or_bytes}"}
                    reader = pypdf.PdfReader(str(file_path_or_bytes))
                elif isinstance(file_path_or_bytes, (bytes, bytearray)):
                    reader = pypdf.PdfReader(io.BytesIO(file_path_or_bytes))

                if reader:
                    num_pages = min(len(reader.pages), max_pages)
                    for i in range(num_pages):
                        page_text = reader.pages[i].extract_text() or ""
                        text_by_page.append(page_text)
            except Exception as e:
                logger.debug(f"pypdf extraction failed or not installed: {e}")
                # Fallback to pdfminer or pypdf2 if available
                try:
                    import fitz  # PyMuPDF
                    doc = fitz.open(file_path_or_bytes)
                    for i in range(min(len(doc), max_pages)):
                        text_by_page.append(doc[i].get_text())
                except Exception as fitz_e:
                    logger.debug(f"fitz extraction failed: {fitz_e}")

            full_text = "\n\n".join(text_by_page)
            return cls._structure_academic_sections(full_text, len(text_by_page))

        return await asyncio.to_thread(_parse)

    @classmethod
    def _structure_academic_sections(cls, full_text: str, total_pages: int) -> Dict[str, Any]:
        """
        Detects standard academic & whitepaper section headers.
        """
        if not full_text:
            return {
                "total_pages": total_pages,
                "abstract": "",
                "sections": {},
                "full_text": "",
            }

        sections: Dict[str, str] = {}
        section_markers = [
            "abstract", "introduction", "background", "related work",
            "methodology", "methods", "architecture", "experimental setup",
            "results", "evaluation", "discussion", "limitations", "conclusion", "references"
        ]

        # Extract abstract
        abstract_m = re.search(r"(?i)abstract\s*[:\-\n]+(.*?)(?=\n\s*(?:1[\.\s]|introduction|keywords))", full_text, re.DOTALL)
        abstract = abstract_m.group(1).strip() if abstract_m else full_text[:800]

        # Break text into section chunks
        pattern = r"(?i)\n\s*(?:[0-9]+\.?\s*)?(" + "|".join(section_markers) + r")\s*[:\-\n]"
        splits = re.split(pattern, full_text)

        if len(splits) > 1:
            for i in range(1, len(splits), 2):
                heading = splits[i].strip().title()
                content = splits[i + 1].strip() if i + 1 < len(splits) else ""
                sections[heading] = content[:3000]

        return {
            "total_pages": total_pages,
            "abstract": abstract[:1500],
            "sections": sections,
            "full_text": full_text[:12000],
        }
