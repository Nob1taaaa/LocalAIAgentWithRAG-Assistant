# LocalAIAgentWithRAG

A local, general-purpose learning assistant that answers with an Ollama model and can retrieve relevant passages from documents you choose. It is no longer tied to the restaurant review demo.

## What it can do

- Index TXT, Markdown, CSV, PDF, and DOCX files, including folders of supported files.
- Keep documents in topic workspaces and search one workspace or all workspaces.
- Cite retrieved filenames and PDF pages or CSV rows in answers.
- Switch between direct answers, step-by-step explanations, study help, quizzes, and Socratic questions.
- Use recent messages as context during the current session.
- Keep the model, embeddings, and vector database local through Ollama and Chroma.

The assistant does not fine-tune itself from questions. Uploaded documents are indexed so relevant passages can be retrieved later. When no uploaded source matches, the configured local model can answer from its built-in knowledge and will identify that it did not use an uploaded source. Web search and cross-session memory are not included yet.

## Requirements

- Python 3.10 or newer
- Ollama running locally
- A chat model and an embedding model available in Ollama

The defaults are `llama3.2:3b` for chat and `mxbai-embed-large` for embeddings. If needed, install them with:

```bash
ollama pull llama3.2:3b
ollama pull mxbai-embed-large
```

Install the Python dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Run the assistant:

```bash
python3 main.py
```

## Commands

```text
/help                    Show all commands
/add "./my study files"  Index a file or folder in the current workspace
/sources                 List indexed files in the current workspace
/remove notes.pdf        Remove an indexed source from the current workspace
/workspace biology       Switch to the biology workspace
/workspace all           Search across all workspaces
/mode explain            Explain step by step
/mode study              Teach and give a practice question
/mode quiz               Quiz one question at a time
/mode socratic           Guide with questions
/mode answer             Return to direct answers
/clear                   Clear recent conversation context
/exit                    Quit
```

Supported file extensions: `.txt`, `.md`, `.csv`, `.pdf`, `.docx`. Quote paths that contain spaces. PDF indexing uses `pypdf`, included in the requirements.

## Configuration

You can override the defaults with environment variables:

```bash
OLLAMA_CHAT_MODEL=llama3.2:3b \
OLLAMA_EMBEDDING_MODEL=mxbai-embed-large \
RAG_DB_DIR=./knowledge_base_db \
python3 main.py
```

The vector database is stored in `knowledge_base_db` by default. Recent conversation context stays in memory for the current run and is cleared when the app exits.
