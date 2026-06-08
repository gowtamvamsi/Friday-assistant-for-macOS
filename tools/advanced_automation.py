"""
tools/advanced_automation.py — Phase 5: "Nuclear" Advanced Capability Tools

Implements three high-power autonomous tools:

1. architect_mode   — Scaffolds a complete coding project from a prompt using the local LLM.
2. content_assassin — Downloads YouTube subtitles and generates Markdown study notes via local LLM.
3. dead_drop        — Uploads a local file to an ephemeral host and generates a QR code.
"""

import os
import json
import logging
import subprocess
import tempfile
import re
import textwrap
from typing import Dict, Any

from tools.registry import register_tool

logger = logging.getLogger("friday.advanced_automation")

# ── Module-level reference to the shared MLXRuntime ───────────────────────────
# Set by main.py after initialization so we can reuse the already-loaded model.
_runtime = None

def set_runtime(runtime):
    """Called by main.py to inject the shared MLXRuntime instance."""
    global _runtime
    _runtime = runtime


def _llm_generate(prompt: str, system: str, max_tokens: int = 2000) -> str:
    """Runs a single LLM generation synchronously using the shared runtime."""
    if _runtime is None:
        raise RuntimeError("MLX runtime not initialized in advanced_automation module.")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt}
    ]
    return _runtime.generate(messages, max_tokens=max_tokens)


# ── Built-in Project Templates ─────────────────────────────────────────────────
# Keyed by keyword tuples → file map. These always work, no LLM needed.

_FLASK_TODO_TEMPLATE = {
    "app.py": '''\
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///todos.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


class Todo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    done = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "done": self.done,
            "created_at": self.created_at.isoformat(),
        }


with app.app_context():
    db.create_all()


@app.route("/todos", methods=["GET"])
def get_todos():
    todos = Todo.query.order_by(Todo.created_at.desc()).all()
    return jsonify([t.to_dict() for t in todos])


@app.route("/todos", methods=["POST"])
def create_todo():
    data = request.get_json()
    if not data or not data.get("title"):
        return jsonify({"error": "title is required"}), 400
    todo = Todo(title=data["title"])
    db.session.add(todo)
    db.session.commit()
    return jsonify(todo.to_dict()), 201


@app.route("/todos/<int:todo_id>", methods=["GET"])
def get_todo(todo_id):
    todo = Todo.query.get_or_404(todo_id)
    return jsonify(todo.to_dict())


@app.route("/todos/<int:todo_id>", methods=["PUT"])
def update_todo(todo_id):
    todo = Todo.query.get_or_404(todo_id)
    data = request.get_json()
    if "title" in data:
        todo.title = data["title"]
    if "done" in data:
        todo.done = bool(data["done"])
    db.session.commit()
    return jsonify(todo.to_dict())


@app.route("/todos/<int:todo_id>", methods=["DELETE"])
def delete_todo(todo_id):
    todo = Todo.query.get_or_404(todo_id)
    db.session.delete(todo)
    db.session.commit()
    return jsonify({"message": "Deleted."})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
''',
    "requirements.txt": "flask\nflask-sqlalchemy\n",
    "README.md": '''\
# Flask Todo REST API

A simple CRUD REST API built with Flask + SQLAlchemy.

## Setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python app.py
```

## Endpoints

| Method | Endpoint         | Description       |
|--------|------------------|-------------------|
| GET    | /todos           | List all todos    |
| POST   | /todos           | Create a todo     |
| GET    | /todos/<id>      | Get one todo      |
| PUT    | /todos/<id>      | Update a todo     |
| DELETE | /todos/<id>      | Delete a todo     |

## Example

```bash
curl -X POST http://localhost:5000/todos -H "Content-Type: application/json" -d '{"title": "Buy milk"}'
curl http://localhost:5000/todos
```
''',
    ".gitignore": "venv/\n__pycache__/\n*.pyc\n*.db\n.env\n",
}

_FASTAPI_TEMPLATE = {
    "main.py": '''\
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

app = FastAPI(title="My API", version="1.0.0")

items: dict = {}
counter = 0


class Item(BaseModel):
    title: str
    description: Optional[str] = None


class ItemOut(Item):
    id: int
    created_at: str


@app.get("/")
def root():
    return {"message": "FastAPI is running!"}


@app.get("/items", response_model=List[ItemOut])
def list_items():
    return list(items.values())


@app.post("/items", response_model=ItemOut, status_code=201)
def create_item(item: Item):
    global counter
    counter += 1
    record = {"id": counter, "created_at": datetime.utcnow().isoformat(), **item.dict()}
    items[counter] = record
    return record


@app.get("/items/{item_id}", response_model=ItemOut)
def get_item(item_id: int):
    if item_id not in items:
        raise HTTPException(status_code=404, detail="Item not found")
    return items[item_id]


@app.delete("/items/{item_id}")
def delete_item(item_id: int):
    if item_id not in items:
        raise HTTPException(status_code=404, detail="Item not found")
    del items[item_id]
    return {"message": "Deleted"}
''',
    "requirements.txt": "fastapi\nuvicorn[standard]\n",
    "README.md": "# FastAPI Project\n\n```bash\npip install -r requirements.txt\nuvicorn main:app --reload\n```\n\nDocs at: http://localhost:8000/docs\n",
    ".gitignore": "venv/\n__pycache__/\n*.pyc\n.env\n",
}

_CLI_TEMPLATE = {
    "main.py": '''\
#!/usr/bin/env python3
"""CLI Tool — generated by Friday."""
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="My CLI Tool")
    subparsers = parser.add_subparsers(dest="command")

    # Example sub-command
    hello_parser = subparsers.add_parser("hello", help="Say hello")
    hello_parser.add_argument("name", nargs="?", default="World")

    args = parser.parse_args()

    if args.command == "hello":
        print(f"Hello, {args.name}!")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
''',
    "requirements.txt": "# Add your dependencies here\n",
    "README.md": "# CLI Tool\n\n```bash\npython main.py hello World\n```\n",
    ".gitignore": "venv/\n__pycache__/\n*.pyc\n.env\n",
}


def _pick_template(prompt: str) -> dict:
    """Picks the best built-in template based on keywords in the prompt."""
    p = prompt.lower()
    if any(k in p for k in ("flask", "todo", "rest api", "crud", "sqlite")):
        return _FLASK_TODO_TEMPLATE
    if any(k in p for k in ("fastapi", "fast api", "async api", "pydantic")):
        return _FASTAPI_TEMPLATE
    if any(k in p for k in ("cli", "command line", "command-line", "argparse", "script")):
        return _CLI_TEMPLATE
    return {}  # No matching template — fall back to LLM


# ── TOOL 1: Architect Mode ─────────────────────────────────────────────────────

@register_tool
def architect_mode(prompt: str, project_name: str = "project") -> Dict[str, Any]:
    """
    Scaffolds a complete coding project from a natural language description.

    Writes all source files to scratch/projects/<project_name>/ and installs
    dependencies into a virtual environment automatically.

    Args:
        prompt (str): Description of the project (e.g., "A Flask REST API for a todo app").
        project_name (str): Directory name for the project (default: "project").

    Returns:
        dict: Status with path to the created project.
    """
    try:
        # Always resolve relative to Friday's root directory
        friday_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        project_dir = os.path.join(friday_root, "scratch", "projects", project_name)
        os.makedirs(project_dir, exist_ok=True)
        logger.info(f"Architect Mode: scaffolding '{project_name}' at {project_dir}")

        # ── Step 1: Try built-in template first ───────────────────────────────
        file_map = _pick_template(prompt)

        # ── Step 2: Fall back to LLM for unknown project types ─────────────────
        if not file_map:
            if _runtime is None:
                # LLM not available yet — write a generic stub so something lands on disk
                logger.warning("Architect Mode: no matching template and LLM not ready. Writing generic stub.")
                file_map = {
                    "main.py": f'"""\n{prompt}\n\nGenerated by Friday — add your code here.\n"""\n\nif __name__ == "__main__":\n    print("Hello from {project_name}!")\n',
                    "requirements.txt": "# Add your dependencies here\n",
                    "README.md": f"# {project_name}\n\n{prompt}\n",
                    ".gitignore": "venv/\n__pycache__/\n*.pyc\n.env\n",
                }
            else:
                logger.info("Architect Mode: no built-in template matched — using LLM to generate project files.")
                system_prompt = (
                    "You are an expert software architect. Given a project description, "
                    "output ONLY a valid JSON object mapping relative file paths to their complete file contents. "
                    "Always include: a main source file, requirements.txt, README.md, and .gitignore. "
                    "Return ONLY the JSON — no explanations, no markdown fences."
                )
                try:
                    llm_response = _llm_generate(
                        prompt=f"Project: {prompt}",
                        system=system_prompt,
                        max_tokens=2500
                    )
                    json_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
                    if json_match:
                        file_map = json.loads(json_match.group())
                    else:
                        raise ValueError("LLM did not return a valid JSON object.")
                except Exception as e:
                    logger.warning(f"Architect Mode LLM generation failed ({e}). Falling back to generic stub.")
                    file_map = {
                        "main.py": f'"""\n{prompt}\n"""\n\nif __name__ == "__main__":\n    print("Hello from {project_name}!")\n',
                        "requirements.txt": "# Add your dependencies here\n",
                        "README.md": f"# {project_name}\n\n{prompt}\n",
                        ".gitignore": "venv/\n__pycache__/\n*.pyc\n.env\n",
                    }

        # ── Step 3: Write files to disk ────────────────────────────────────────
        files_created = []
        for rel_path, content in file_map.items():
            full_path = os.path.join(project_dir, rel_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            files_created.append(rel_path)
            logger.info(f"Architect Mode: wrote {rel_path}")

        # ── Step 4: Create venv and install dependencies ───────────────────────
        req_path = os.path.join(project_dir, "requirements.txt")
        venv_dir = os.path.join(project_dir, "venv")
        if os.path.exists(req_path):
            logger.info("Architect Mode: creating virtual environment...")
            subprocess.run(["python3", "-m", "venv", "venv"], cwd=project_dir, capture_output=True)
            pip = os.path.join(venv_dir, "bin", "pip")
            if os.path.exists(pip):
                subprocess.run([pip, "install", "-r", "requirements.txt"], cwd=project_dir, capture_output=True)
                logger.info("Architect Mode: dependencies installed.")

        summary = f"Created {len(files_created)} files: {', '.join(files_created)}"
        logger.info(f"Architect Mode: done. {summary}")

        return {
            "status": "success",
            "message": f"Project '{project_name}' is ready at scratch/projects/{project_name}/. {summary}"
        }

    except Exception as e:
        logger.exception("Architect Mode failed.")
        return {"status": "error", "message": f"Architect Mode failed: {e}"}


# ──────────────────────────────────────────────────────────────────────────────
# TOOL 2: Content Assassin
# ──────────────────────────────────────────────────────────────────────────────

@register_tool
def content_assassin(youtube_url: str) -> Dict[str, Any]:
    """
    Downloads YouTube subtitles and generates comprehensive Markdown study notes using the local LLM.

    Args:
        youtube_url (str): Full YouTube video URL (e.g., https://www.youtube.com/watch?v=XXXXXXXXXXX).

    Returns:
        dict: Status with the path to the generated Markdown notes file.
    """
    try:
        # Extract video ID
        match = re.search(r'(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})', youtube_url)
        if not match:
            return {"status": "error", "message": "Could not extract video ID from the URL."}
        video_id = match.group(1)

        logger.info(f"Content Assassin: fetching transcript for video {video_id}...")

        # Try youtube_transcript_api first (faster, no download)
        transcript_text = None
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
            transcript_text = " ".join(entry["text"] for entry in transcript_list)
            logger.info(f"Content Assassin: transcript fetched ({len(transcript_text)} chars).")
        except Exception as e:
            logger.warning(f"youtube_transcript_api failed ({e}), falling back to yt-dlp...")

        # Fallback: use yt-dlp to download subtitle file
        if not transcript_text:
            with tempfile.TemporaryDirectory() as tmpdir:
                result = subprocess.run(
                    ["yt-dlp", "--skip-download", "--write-auto-subs",
                     "--sub-lang", "en", "--sub-format", "vtt",
                     "-o", os.path.join(tmpdir, "%(id)s.%(ext)s"),
                     youtube_url],
                    capture_output=True, text=True, timeout=60
                )
                vtt_files = [f for f in os.listdir(tmpdir) if f.endswith(".vtt")]
                if vtt_files:
                    with open(os.path.join(tmpdir, vtt_files[0]), "r") as f:
                        raw = f.read()
                    # Strip VTT formatting
                    lines = [l.strip() for l in raw.splitlines()
                             if l.strip() and not l.startswith("WEBVTT")
                             and "-->" not in l and not l.isdigit()]
                    transcript_text = " ".join(lines)
                else:
                    return {"status": "error", "message": "Could not retrieve subtitles for this video."}

        # Trim transcript if very long
        max_chars = 12000
        if len(transcript_text) > max_chars:
            transcript_text = transcript_text[:max_chars] + "... [transcript truncated]"

        # Generate study notes using the local LLM
        logger.info("Content Assassin: generating study notes with local LLM...")
        system_prompt = textwrap.dedent("""
            You are an expert educator and note-taker. Given a video transcript, generate structured, 
            comprehensive Markdown study notes. Include:
            - A # Title and ## Summary section
            - ## Key Concepts with bullet points
            - ## Detailed Notes organized by topic
            - ## Key Takeaways at the end
            Format cleanly with proper Markdown. Be concise but thorough.
        """).strip()

        notes = _llm_generate(
            prompt=f"YouTube Transcript:\n\n{transcript_text}",
            system=system_prompt,
            max_tokens=2000
        )

        # Save notes to file
        output_dir = os.path.abspath("scratch")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"notes_{video_id}.md")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"<!-- Source: {youtube_url} -->\n\n")
            f.write(notes)

        logger.info(f"Content Assassin: notes saved to {output_path}")
        return {
            "status": "success",
            "message": f"Study notes generated and saved to scratch/notes_{video_id}.md"
        }

    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Subtitle download timed out."}
    except Exception as e:
        logger.exception("Content Assassin failed.")
        return {"status": "error", "message": f"Content Assassin failed: {e}"}


# ──────────────────────────────────────────────────────────────────────────────
# TOOL 3: Dead Drop
# ──────────────────────────────────────────────────────────────────────────────

def _generate_terminal_qr(url: str) -> str:
    """Generates a compact text-based QR code string for terminal display."""
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1,
            border=1
        )
        qr.add_data(url)
        qr.make(fit=True)
        # Render as ASCII using unicode block characters
        lines = []
        matrix = qr.get_matrix()
        for row in matrix:
            line = "".join("██" if cell else "  " for cell in row)
            lines.append(line)
        return "\n".join(lines)
    except Exception:
        return f"[QR Code: {url}]"


@register_tool
def dead_drop(file_path: str) -> Dict[str, Any]:
    """
    Uploads a local file to an ephemeral file-sharing service and generates a QR code for mobile download.

    Args:
        file_path (str): Absolute or relative path to the file to share.

    Returns:
        dict: Status with the download URL.
    """
    try:
        import requests

        if not os.path.exists(file_path):
            return {"status": "error", "message": f"File not found: {file_path}"}

        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        filename = os.path.basename(file_path)

        logger.info(f"Dead Drop: uploading '{filename}' ({file_size_mb:.1f} MB) to file.io...")

        # Upload to file.io (free, ephemeral, no account needed)
        with open(file_path, "rb") as f:
            response = requests.post(
                "https://file.io",
                files={"file": (filename, f)},
                data={"expires": "7d"},  # Auto-expires in 7 days
                timeout=60
            )

        if not response.ok:
            # Fallback to oshi.at
            logger.warning(f"file.io upload failed ({response.status_code}), trying oshi.at...")
            with open(file_path, "rb") as f:
                response = requests.post(
                    "https://oshi.at",
                    files={"f": (filename, f)},
                    timeout=60
                )
            if not response.ok:
                return {"status": "error", "message": f"Upload failed on all services. Status: {response.status_code}"}
            # oshi.at returns the URL in plain text
            download_url = response.text.strip().split("\n")[0]
        else:
            data = response.json()
            if not data.get("success"):
                return {"status": "error", "message": f"Upload failed: {data.get('message', 'Unknown error')}"}
            download_url = data["link"]

        # Generate QR code for terminal display
        qr_display = _generate_terminal_qr(download_url)

        # Print QR to terminal
        print(f"\n{'═'*50}")
        print(f"  Dead Drop: {filename}")
        print(f"  URL: {download_url}")
        print(f"{'═'*50}")
        print(qr_display)
        print(f"{'═'*50}\n")

        logger.info(f"Dead Drop: '{filename}' uploaded → {download_url}")

        return {
            "status": "success",
            "message": f"File '{filename}' uploaded. Download URL: {download_url}. QR code displayed in terminal."
        }

    except Exception as e:
        logger.exception("Dead Drop failed.")
        return {"status": "error", "message": f"Dead Drop failed: {e}"}
