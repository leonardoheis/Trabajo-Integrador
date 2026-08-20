# Intentionally empty. Importing a submodule executes its parent package first, so a
# re-export barrel here would pull chromadb into every `vector_store` import. Import from
# the concrete module instead -- see knowledge/README.md.
