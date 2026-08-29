import os
import logging
from typing import List, Dict, Any

logger = logging.getLogger("JARVIS.DocumentParser")

class DocumentParser:
    """
    Utility to parse files (like txt, py, md, json, html) and split them into
    overlapping text segments for semantic vector indexing.
    """
    def __init__(self, chunk_size: int = 800, overlap: int = 80):
        self.chunk_size = chunk_size
        self.overlap = overlap
        self._extractor = None

    @property
    def extractor(self):
        if self._extractor is None:
            from modules.filesystem.document_extractor import DocumentExtractor
            self._extractor = DocumentExtractor()
        return self._extractor

    def chunk_file(self, file_path: str) -> List[Dict[str, Any]]:
        """Parse and split a document into overlapping text chunks."""
        if not os.path.exists(file_path):
            logger.warning(f"File not found: {file_path}")
            return []
            
        try:
            ext = os.path.splitext(file_path)[1].lower()
            if ext in (".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg", ".pptx", ".csv", ".json", ".yaml", ".yml", ".xml", ".html", ".htm"):
                logger.info(f"Extracting content for document file: {file_path}")
                result = self.extractor.extract(file_path)
                if not result.success:
                    content = f"Binary file name: {os.path.basename(file_path)}, Extension: {ext}, Size: {os.path.getsize(file_path)} bytes. Error: {result.error}"
                    return self.chunk_text(content, file_path)
                
                # Check for PDF to do page-by-page chunking
                if ext == ".pdf" and "page_texts" in result.metadata:
                    chunks = []
                    page_texts = result.metadata["page_texts"]
                    for idx, page_text in enumerate(page_texts):
                        page_num = idx + 1
                        if not page_text.strip():
                            continue
                        page_chunks = self.chunk_text(page_text, file_path)
                        # Add page_number to chunk metadata
                        for chunk in page_chunks:
                            chunk["metadata"]["page_number"] = page_num
                            if "pages" in result.metadata and idx < len(result.metadata["pages"]):
                                chunk["metadata"]["extraction_method"] = result.metadata["pages"][idx]["method"]
                        chunks.extend(page_chunks)
                    return chunks
                
                # Check for XLSX to do sheet-by-sheet chunking
                elif ext == ".xlsx" and "sheet_texts" in result.metadata:
                    chunks = []
                    sheet_texts = result.metadata["sheet_texts"]
                    for sheet_name, sheet_text in sheet_texts.items():
                        if not sheet_text.strip():
                            continue
                        sheet_chunks = self.chunk_text(sheet_text, file_path)
                        for chunk in sheet_chunks:
                            chunk["metadata"]["sheet_name"] = sheet_name
                        chunks.extend(sheet_chunks)
                    return chunks
                
                # DOCX and images are single content strings
                else:
                    return self.chunk_text(result.text, file_path)
                    
            elif ext in (".zip", ".tar", ".gz"):
                # Binary files - read name/metadata
                logger.info(f"Ingesting metadata preview for binary file: {file_path}")
                content = f"Binary file name: {os.path.basename(file_path)}, Extension: {ext}, Size: {os.path.getsize(file_path)} bytes."
                return self.chunk_text(content, file_path)
            else:
                # Text files
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    
                if not content.strip():
                    return []
                    
                return self.chunk_text(content, file_path)
        except Exception as e:
            logger.error(f"Error parsing file '{file_path}': {e}")
            return []

    def chunk_text(self, text: str, file_path: str) -> List[Dict[str, Any]]:
        """Split raw text into overlapping segments."""
        chunks = []
        filename = os.path.basename(file_path)
        
        start = 0
        chunk_idx = 0
        text_len = len(text)
        
        while start < text_len:
            end = min(start + self.chunk_size, text_len)
            chunk_text = text[start:end]
            
            chunks.append({
                "chunk_id": f"{filename}_chunk_{chunk_idx}_{start}",
                "text": chunk_text,
                "metadata": {
                    "file_path": file_path,
                    "filename": filename,
                    "chunk_index": chunk_idx,
                    "char_start": start,
                    "char_end": end
                }
            })
            
            if end == text_len:
                break
            start += (self.chunk_size - self.overlap)
            chunk_idx += 1
            
        return chunks
