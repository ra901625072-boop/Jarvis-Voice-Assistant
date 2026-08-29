import os
import sys
import logging

# Set up backend folder in sys.path
backend_path = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "apps", "backend"))
sys.path.insert(0, backend_path)

# Configure basic logging to stdout
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("JarvisBackfillIndexer")

def main():
    logger.info("Initializing Jarvis Backfill Indexer...")
    
    try:
        from modules.filesystem.file_manager import FileManager
        from modules.filesystem.semantic_engine import SemanticEngine
        from modules.filesystem.document_parser import DocumentParser
    except ImportError as err:
        logger.error(f"Failed to import backend modules: {err}")
        logger.error("Please make sure you run this script with the virtual environment activated.")
        sys.exit(1)
        
    file_mgr = FileManager()
    db_dir = os.path.dirname(file_mgr.db_path)
    logger.info(f"Database directory resolved to: {db_dir}")
    
    se = SemanticEngine(db_dir)
    parser = DocumentParser()
    
    paths_to_scan = file_mgr.indexer.get_default_paths()
    logger.info(f"Default monitored paths to scan: {paths_to_scan}")
    
    supported_extensions = (".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".pptx", ".csv", ".json", ".yaml", ".yml", ".xml", ".html", ".htm")
    ignored_dirs = {
        "node_modules", ".git", "venv", "__pycache__", 
        ".pytest_cache", ".agents", ".gemini", "logs", 
        "database", "chroma", "temp", "tmp", ".ruff_cache"
    }
    
    total_processed = 0
    total_indexed_chunks = 0
    
    for root_path in paths_to_scan:
        if not os.path.exists(root_path):
            logger.warning(f"Path does not exist, skipping: {root_path}")
            continue
            
        logger.info(f"Scanning directory: {root_path}")
        for root, dirs, files in os.walk(root_path):
            # Prune ignored directories in-place
            dirs[:] = [d for d in dirs if d.lower() not in ignored_dirs]
            
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in supported_extensions:
                    full_path = os.path.normpath(os.path.join(root, file))
                    logger.info(f"Processing and backfilling: {full_path}")
                    try:
                        chunks = parser.chunk_file(full_path)
                        if chunks:
                            se.index_document_chunks(full_path, chunks)
                            total_processed += 1
                            total_indexed_chunks += len(chunks)
                            logger.info(f"Successfully indexed {len(chunks)} chunks for {file}")
                        else:
                            logger.info(f"No text extracted/chunks generated for {file}")
                    except Exception as ex:
                        logger.error(f"Error processing file {full_path}: {ex}", exc_info=True)
                        
    logger.info(f"Backfill indexing completed. Processed {total_processed} files, indexed a total of {total_indexed_chunks} chunks.")

if __name__ == "__main__":
    main()
