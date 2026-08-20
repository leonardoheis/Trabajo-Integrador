# Intentionally empty. Importing any submodule executes this package first, so a
# re-export barrel here would load chromadb, sentence_transformers, anthropic and
# llama_cpp on every `knowledge.*` import -- including in tests that need none of them.
# Import from the capability module instead -- see knowledge/README.md.
