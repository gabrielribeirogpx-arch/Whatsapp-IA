import unittest

from app.services.ai_model_validation import validate_chat_model, validate_embedding_model


class AIModelValidationTest(unittest.TestCase):
    def test_accepts_new_gemini_chat_models(self):
        for model in ["gemini-3.1-flash-lite", "gemini-3-flash", "gemini-3.5-flash"]:
            with self.subTest(model=model):
                self.assertEqual(validate_chat_model(model), model)

    def test_blocks_embedding_model_as_chat_model(self):
        with self.assertRaises(ValueError):
            validate_chat_model("gemini-embedding-001")

    def test_accepts_embedding_model(self):
        self.assertEqual(validate_embedding_model("gemini-embedding-001"), "gemini-embedding-001")

    def test_blocks_chat_model_as_embedding_model(self):
        with self.assertRaises(ValueError):
            validate_embedding_model("gemini-2.5-flash")


if __name__ == "__main__":
    unittest.main()
