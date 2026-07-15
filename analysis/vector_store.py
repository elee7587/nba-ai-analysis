"""
Storing documents with embeddings - converting text into vectors so we can do semantic search
three types of documents:
Game analyses
Corrected analyses
Narratives
"""
# analysis/vector_store.py
import chromadb
from loguru import logger
import json
from datetime import datetime

class NBAVectorStore:

    def __init__(self):
        # initialize chromadb client
        chroma_client = chromadb.PersistentClient(path="./chroma_db")
        # create or get collections
        self.analysis_collection = chroma_client.get_or_create_collection("game_analyses")
        self.corrected_collection = chroma_client.get_or_create_collection("corrected_analyses")
        self.narrative_collection = chroma_client.get_or_create_collection("narratives")
        logger.info("Initialized ChromaDB client and collections for game analyses, corrected analyses, and narratives.")

    def store_analysis(self, game_id: str, findings: dict):
        # store analyst findings
        self.analysis_collection.upsert(
            documents=[json.dumps(findings)],
            metadatas=[{"game_id": game_id, "timestamp": str(datetime.utcnow())}],
            ids=[f"analysis_{game_id}"]
        )

    def store_correction(self, game_id: str, correction: dict):
        # store human correction
        self.corrected_collection.upsert(
            documents=[json.dumps(correction)],
            metadatas=[{"game_id": game_id, "timestamp": str(datetime.utcnow())}],
            ids=[f"correction_{game_id}"]
        )

    def store_narrative(self, game_id: str, narrative: dict):
        # store final narrative
        self.narrative_collection.upsert(
            documents=[json.dumps(narrative)],
            metadatas=[{"game_id": game_id, "timestamp": str(datetime.utcnow())}],
            ids=[f"narrative_{game_id}"]
        )

    def get_similar_games(self, query: str, n_results: int = 3) -> list:
        results = self.analysis_collection.query(
            query_texts=[query],
            n_results=n_results
        )
        return results['documents'][0] if results['documents'] else []
    
    def get_corrections(self, game_id: str) -> dict | None:
        """Retrieve corrections for a specific game if they exist"""
        try:
            result = self.corrected_collection.get(
                ids=[f"correction_{game_id}"]
            )
            if result['documents']:
                return json.loads(result['documents'][0])
            return None
        except Exception:
            return None