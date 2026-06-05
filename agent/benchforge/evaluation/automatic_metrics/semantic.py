"""bleu、bertscore、semantic_similarity 指标。"""

from .base import AutoMetric


class BleuMetric(AutoMetric):
    name = "bleu"

    def compute(self, question: dict, prediction: str, context: dict | None = None) -> float | None:
        try:
            from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
            ref = str(question.get("answer", "")).lower().split()
            pred = prediction.lower().split()
            if not ref or not pred:
                return 0.0
            return sentence_bleu(
                [ref], pred,
                smoothing_function=SmoothingFunction().method1,
            )
        except ImportError:
            return None


class BertScoreMetric(AutoMetric):
    name = "bertscore"

    def compute(self, question: dict, prediction: str, context: dict | None = None) -> float | None:
        try:
            from bert_score import score as bert_score
            ref = str(question.get("answer", ""))
            P, R, F1 = bert_score([prediction], [ref], lang="en", verbose=False)
            return float(F1[0])
        except ImportError:
            return None


class SemanticSimilarityMetric(AutoMetric):
    name = "semantic_similarity"

    _model = None

    def _get_model(self):
        if SemanticSimilarityMetric._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                SemanticSimilarityMetric._model = SentenceTransformer("all-MiniLM-L6-v2")
            except ImportError:
                return None
        return SemanticSimilarityMetric._model

    def compute(self, question: dict, prediction: str, context: dict | None = None) -> float | None:
        model = self._get_model()
        if model is None:
            return None
        import numpy as np
        ref = str(question.get("answer", ""))
        embs = model.encode([prediction, ref], convert_to_numpy=True, normalize_embeddings=True)
        return float(np.dot(embs[0], embs[1]))
