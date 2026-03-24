"""
vector_store.py - FAISS-based vector store for rules documents
"""
import os
import pickle
import numpy as np
from typing import List, Dict, Any

# We'll use a simple embedding approach that works without external API calls
# In production, replace with OpenAI embeddings


class SimpleEmbedder:
    """Simple TF-IDF-like embedder for demo purposes."""
    
    def __init__(self):
        self.vocab = {}
        self.idf = {}
        self.fitted = False
    
    def _tokenize(self, text: str) -> List[str]:
        import re
        return re.findall(r'\b\w+\b', text.lower())
    
    def fit(self, texts: List[str]):
        from collections import Counter
        import math
        all_tokens = []
        doc_tokens = []
        for text in texts:
            tokens = set(self._tokenize(text))
            doc_tokens.append(tokens)
            all_tokens.extend(tokens)
        
        vocab_set = set(all_tokens)
        self.vocab = {word: i for i, word in enumerate(sorted(vocab_set))}
        
        N = len(texts)
        for word in self.vocab:
            df = sum(1 for tokens in doc_tokens if word in tokens)
            self.idf[word] = math.log((N + 1) / (df + 1)) + 1
        
        self.fitted = True
    
    def embed(self, text: str) -> np.ndarray:
        tokens = self._tokenize(text)
        from collections import Counter
        tf = Counter(tokens)
        
        vec = np.zeros(len(self.vocab))
        for word, count in tf.items():
            if word in self.vocab:
                idx = self.vocab[word]
                tfidf = (count / len(tokens)) * self.idf.get(word, 1.0)
                vec[idx] = tfidf
        
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.astype(np.float32)


class RulesVectorStore:
    """FAISS vector store for rules documents."""
    
    def __init__(self, store_path: str = "data/faiss_store"):
        self.store_path = store_path
        self.embedder = SimpleEmbedder()
        self.chunks: List[Dict[str, Any]] = []
        self.index = None
        self._loaded = False
    
    def _chunk_rules(self, rules_text: str) -> List[Dict[str, Any]]:
        """Split rules document into chunks."""
        chunks = []
        lines = rules_text.strip().split('\n')
        current_rule = []
        current_rule_id = None
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Detect rule headers (numbered lines)
            import re
            if re.match(r'^\d+\.', line):
                if current_rule and current_rule_id is not None:
                    chunks.append({
                        'rule_id': current_rule_id,
                        'text': '\n'.join(current_rule),
                        'type': 'rule'
                    })
                current_rule_id = line
                current_rule = [line]
            else:
                current_rule.append(line)
        
        if current_rule:
            chunks.append({
                'rule_id': current_rule_id or 'general',
                'text': '\n'.join(current_rule),
                'type': 'rule'
            })
        
        # Also add full document as one chunk
        chunks.append({
            'rule_id': 'full_document',
            'text': rules_text,
            'type': 'full'
        })
        
        return chunks
    
    def build_index(self, rules_text: str):
        """Build FAISS index from rules document."""
        try:
            import faiss
        except ImportError:
            raise ImportError("faiss-cpu not installed. Run: pip install faiss-cpu")
        
        self.chunks = self._chunk_rules(rules_text)
        texts = [c['text'] for c in self.chunks]
        
        # Fit embedder and create embeddings
        self.embedder.fit(texts)
        embeddings = np.array([self.embedder.embed(t) for t in texts])
        
        dim = embeddings.shape[1]
        self.index = faiss.IndexFlatIP(dim)  # Inner product (cosine with normalized vecs)
        self.index.add(embeddings)
        
        # Save to disk
        os.makedirs(self.store_path, exist_ok=True)
        faiss.write_index(self.index, os.path.join(self.store_path, "rules.index"))
        with open(os.path.join(self.store_path, "chunks.pkl"), 'wb') as f:
            pickle.dump(self.chunks, f)
        with open(os.path.join(self.store_path, "embedder.pkl"), 'wb') as f:
            pickle.dump(self.embedder, f)
        
        self._loaded = True
        return len(self.chunks)
    
    def load_index(self) -> bool:
        """Load existing FAISS index from disk."""
        try:
            import faiss
            index_path = os.path.join(self.store_path, "rules.index")
            chunks_path = os.path.join(self.store_path, "chunks.pkl")
            embedder_path = os.path.join(self.store_path, "embedder.pkl")
            
            if not all(os.path.exists(p) for p in [index_path, chunks_path, embedder_path]):
                return False
            
            self.index = faiss.read_index(index_path)
            with open(chunks_path, 'rb') as f:
                self.chunks = pickle.load(f)
            with open(embedder_path, 'rb') as f:
                self.embedder = pickle.load(f)
            
            self._loaded = True
            return True
        except Exception:
            return False
    
    def search(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """Search for relevant rules."""
        if not self._loaded:
            raise ValueError("Index not built or loaded.")
        
        import faiss
        query_vec = self.embedder.embed(query).reshape(1, -1)
        scores, indices = self.index.search(query_vec, min(top_k, len(self.chunks)))
        
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0:
                chunk = self.chunks[idx].copy()
                chunk['score'] = float(score)
                results.append(chunk)
        
        return results
    
    def get_all_rules(self) -> str:
        """Get the full rules document text."""
        if not self._loaded:
            return ""
        for chunk in self.chunks:
            if chunk.get('type') == 'full':
                return chunk['text']
        return '\n\n'.join(c['text'] for c in self.chunks if c.get('type') == 'rule')
    
    def is_ready(self) -> bool:
        return self._loaded
