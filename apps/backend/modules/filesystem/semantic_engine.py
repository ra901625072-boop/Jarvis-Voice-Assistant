import logging
import os

logger = logging.getLogger("JARVIS.SemanticEngine")

class SemanticEngine:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._collection = None
        self._init_chroma()
        
    def _init_chroma(self):
        try:
            import chromadb
            client = chromadb.PersistentClient(path=os.path.join(self.db_path, "chroma"))
            self._collection = client.get_or_create_collection(name="file_semantics")
        except ImportError:
            logger.warning("chromadb not installed. Semantic search disabled.")
            self._collection = None
        except Exception as e:
            logger.error(f"Failed to init ChromaDB: {e}")
            self._collection = None
            
    def index_file(self, path: str, content_preview: str):
        if not self._collection:
            return
        try:
            self._collection.upsert(
                documents=[content_preview],
                metadatas=[{"path": path}],
                ids=[path]
            )
        except Exception as e:
            logger.debug(f"Failed to index file in chromadb: {e}")
            
    def index_document_chunks(self, path: str, chunks: list):
        if not self._collection:
            return
        try:
            try:
                self._collection.delete(where={"file_path": path})
            except Exception as delete_ex:
                logger.debug(f"Failed to delete old chunks for path '{path}': {delete_ex}")
                
            documents = []
            metadatas = []
            ids = []
            for chunk in chunks:
                documents.append(chunk["text"])
                metadatas.append(chunk["metadata"])
                ids.append(chunk["chunk_id"])
                
            if documents:
                self._collection.upsert(
                    documents=documents,
                    metadatas=metadatas,
                    ids=ids
                )
                logger.info(f"Indexed {len(documents)} chunks for file: {path}")
        except Exception as e:
            logger.debug(f"Failed to index document chunks in chromadb: {e}")

    async def search(self, query: str, limit: int = 3) -> list:
        if not self._collection:
            return []
        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=limit
            )
            if results and results["metadatas"] and results["metadatas"][0]:
                return [meta["path"] for meta in results["metadatas"][0]]
        except Exception as e:
            logger.debug(f"Semantic search failed: {e}")
        return []
