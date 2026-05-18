"""
database.py — SQLite Data Access Layer
Pet Emergency First-Aid Web Application
Coding Standard: PEP 8
Reference: https://peps.python.org/pep-0008/

Responsibilities:
  - Define and create all database tables on first run.
  - Seed tables from JSON source files (one-time, only if tables are empty).
  - Provide query helper functions used by app.py controllers.

Database: petfirstaid.db (SQLite, created automatically in project root)
Tables:
  pets              — supported pet types
  emergency_categories — supported emergency category names
  guides            — first-aid guides (steps, warnings stored as JSON text)
  videos            — instructional video metadata
  quizzes           — quiz metadata
  questions         — individual quiz questions (linked to quiz)
  answers           — answer options for each question
  feedback          — user-submitted ratings and comments
  quiz_results      — scored quiz attempts
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "petfirstaid.db")
DATA_DIR = os.path.join(BASE_DIR, "data")


# ---------------------------------------------------------------------------
# Connection Helper
# ---------------------------------------------------------------------------

@contextmanager
def get_db():
    """
    Context manager that yields a SQLite connection with row_factory set
    so rows are accessible as dicts. Commits on success, rolls back on error.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # Safe concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_to_dict(row):
    """Convert a sqlite3.Row to a plain dict."""
    return dict(row) if row else None


def rows_to_list(rows):
    """Convert a list of sqlite3.Row objects to a list of dicts."""
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Schema Creation
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pets (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS emergency_categories (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS guides (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pet_type            TEXT NOT NULL,
    emergency_category  TEXT NOT NULL,
    title               TEXT NOT NULL,
    summary             TEXT NOT NULL,
    warning             TEXT,
    steps_json          TEXT NOT NULL,   -- JSON array of step strings
    next_steps_json     TEXT NOT NULL,   -- JSON array of recommendation strings
    video_id            INTEGER,
    approved            INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (video_id) REFERENCES videos(id)
);

CREATE TABLE IF NOT EXISTS videos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guide_id    INTEGER NOT NULL,
    title       TEXT NOT NULL,
    description TEXT,
    duration    TEXT,
    url         TEXT NOT NULL,
    caption     INTEGER NOT NULL DEFAULT 0,
    approved    INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (guide_id) REFERENCES guides(id)
);

CREATE TABLE IF NOT EXISTS quizzes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pet_type    TEXT NOT NULL,
    topic       TEXT NOT NULL,
    difficulty  TEXT NOT NULL DEFAULT 'Beginner',
    approved    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS questions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id     INTEGER NOT NULL,
    text        TEXT NOT NULL,
    correct     INTEGER NOT NULL,   -- 0-based index of the correct answer
    explanation TEXT NOT NULL,
    FOREIGN KEY (quiz_id) REFERENCES quizzes(id)
);

CREATE TABLE IF NOT EXISTS answers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    option_text TEXT NOT NULL,
    option_order INTEGER NOT NULL,  -- 0-based display order
    FOREIGN KEY (question_id) REFERENCES questions(id)
);

CREATE TABLE IF NOT EXISTS feedback (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    content_type TEXT NOT NULL,     -- 'guide', 'video', or 'quiz'
    content_id   INTEGER NOT NULL,
    rating       INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
    comment      TEXT,              -- optional, max 200 chars enforced in app
    submitted_at TEXT NOT NULL      -- ISO-8601 timestamp
);

CREATE TABLE IF NOT EXISTS quiz_results (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id      INTEGER NOT NULL,
    score        INTEGER NOT NULL,
    total        INTEGER NOT NULL,
    percentage   INTEGER NOT NULL,
    answers_json TEXT NOT NULL,     -- JSON snapshot of per-question results
    completed_at TEXT NOT NULL,     -- ISO-8601 timestamp
    FOREIGN KEY (quiz_id) REFERENCES quizzes(id)
);
"""


def create_tables():
    """Create all tables if they do not already exist."""
    with get_db() as conn:
        conn.executescript(SCHEMA_SQL)


# ---------------------------------------------------------------------------
# Seeding — load from JSON files (runs only when tables are empty)
# ---------------------------------------------------------------------------

def _load_json(filename):
    """Read a JSON file from the data directory."""
    path = os.path.join(DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def seed_database():
    """
    Populate all tables from JSON source files.
    Each table is only seeded when it contains zero rows, so this is
    safe to call on every startup without duplicating data.

    Seeding order: pets/categories -> guides (no FK to videos yet) ->
    videos -> update guides.video_id -> quizzes/questions/answers.
    Foreign key enforcement is suspended during seeding to allow the
    circular reference between guides and videos to be resolved in two passes.
    """
    with get_db() as conn:
        # Suspend FK enforcement for the seed transaction only
        conn.execute("PRAGMA foreign_keys=OFF")

        # ── Pets and categories ──────────────────────────────────────────────
        if conn.execute("SELECT COUNT(*) FROM pets").fetchone()[0] == 0:
            source = _load_json("guides.json")
            for name in source["pets"]:
                conn.execute("INSERT INTO pets (name) VALUES (?)", (name,))
            for name in source["emergency_categories"]:
                conn.execute(
                    "INSERT INTO emergency_categories (name) VALUES (?)", (name,)
                )

        # ── Guides (seed first without video_id to break circular FK) ────────
        if conn.execute("SELECT COUNT(*) FROM guides").fetchone()[0] == 0:
            raw_guides = _load_json("guides.json")["guides"]
            for g in raw_guides:
                conn.execute(
                    """
                    INSERT INTO guides
                        (id, pet_type, emergency_category, title, summary,
                         warning, steps_json, next_steps_json, video_id, approved)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 1)
                    """,
                    (
                        g["id"],
                        g["pet_type"],
                        g["emergency_category"],
                        g["title"],
                        g["summary"],
                        g.get("warning"),
                        json.dumps(g["steps"]),
                        json.dumps(g["next_steps"]),
                    ),
                )

        # ── Videos ───────────────────────────────────────────────────────────
        if conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0:
            raw_videos = _load_json("videos.json")
            for v in raw_videos:
                conn.execute(
                    """
                    INSERT INTO videos
                        (id, guide_id, title, description, duration, url, caption, approved)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        v["id"],
                        v["guide_id"],
                        v["title"],
                        v.get("description", ""),
                        v.get("duration", ""),
                        v["url"],
                        1 if v.get("caption") else 0,
                        1 if v.get("approved", True) else 0,
                    ),
                )

            # Now set video_id on guides that have an associated video
            raw_guides = _load_json("guides.json")["guides"]
            for g in raw_guides:
                if g.get("video_id"):
                    conn.execute(
                        "UPDATE guides SET video_id = ? WHERE id = ?",
                        (g["video_id"], g["id"]),
                    )

        # ── Quizzes, Questions, Answers ──────────────────────────────────────
        if conn.execute("SELECT COUNT(*) FROM quizzes").fetchone()[0] == 0:
            raw_quizzes = _load_json("quizzes.json")
            for q in raw_quizzes:
                conn.execute(
                    """
                    INSERT INTO quizzes (id, pet_type, topic, difficulty, approved)
                    VALUES (?, ?, ?, ?, 1)
                    """,
                    (q["id"], q["pet_type"], q["topic"], q.get("difficulty", "Beginner")),
                )
                for question in q["questions"]:
                    cur = conn.execute(
                        """
                        INSERT INTO questions (quiz_id, text, correct, explanation)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            q["id"],
                            question["text"],
                            question["correct"],
                            question["explanation"],
                        ),
                    )
                    q_row_id = cur.lastrowid
                    for idx, option_text in enumerate(question["options"]):
                        conn.execute(
                            """
                            INSERT INTO answers (question_id, option_text, option_order)
                            VALUES (?, ?, ?)
                            """,
                            (q_row_id, option_text, idx),
                        )

        # Re-enable FK enforcement after seeding is complete
        conn.execute("PRAGMA foreign_keys=ON")


# ---------------------------------------------------------------------------
# Query Helpers — Guides
# ---------------------------------------------------------------------------

def get_all_pets(conn):
    """Return list of all pet type name strings."""
    rows = conn.execute("SELECT name FROM pets ORDER BY id").fetchall()
    return [r["name"] for r in rows]


def get_all_categories(conn):
    """Return list of all emergency category name strings."""
    rows = conn.execute(
        "SELECT name FROM emergency_categories ORDER BY id"
    ).fetchall()
    return [r["name"] for r in rows]


def get_guide_by_id(conn, guide_id):
    """
    Fetch a single guide row by primary key.
    Deserialises steps_json and next_steps_json back to Python lists.
    Returns a dict or None.
    """
    row = conn.execute(
        "SELECT * FROM guides WHERE id = ?", (guide_id,)
    ).fetchone()
    if not row:
        return None
    guide = row_to_dict(row)
    guide["steps"] = json.loads(guide.pop("steps_json"))
    guide["next_steps"] = json.loads(guide.pop("next_steps_json"))
    return guide


def search_guides(conn, pet_type=None, emergency_category=None, keyword=None,
                  max_results=10, keyword_max_len=50):
    """
    Filter guides by pet_type, emergency_category, and/or keyword.
    Returns a list of guide dicts (steps and next_steps deserialised).
    """
    sql = "SELECT * FROM guides WHERE approved = 1"
    params = []

    if pet_type:
        sql += " AND LOWER(pet_type) = LOWER(?)"
        params.append(pet_type)

    if emergency_category:
        sql += " AND LOWER(emergency_category) = LOWER(?)"
        params.append(emergency_category)

    if keyword:
        kw = keyword.strip()[:keyword_max_len].lower()
        sql += (
            " AND (LOWER(title) LIKE ? OR LOWER(summary) LIKE ?"
            " OR LOWER(pet_type) LIKE ? OR LOWER(emergency_category) LIKE ?)"
        )
        like = f"%{kw}%"
        params.extend([like, like, like, like])

    sql += f" LIMIT {int(max_results)}"
    rows = conn.execute(sql, params).fetchall()

    results = []
    for row in rows:
        g = row_to_dict(row)
        g["steps"] = json.loads(g.pop("steps_json"))
        g["next_steps"] = json.loads(g.pop("next_steps_json"))
        results.append(g)
    return results


def get_alternative_guides(conn, guide_id, pet_type, emergency_category, limit=3):
    """Return up to `limit` guides that share the same pet or category."""
    rows = conn.execute(
        """
        SELECT * FROM guides
        WHERE id != ? AND approved = 1
          AND (LOWER(pet_type) = LOWER(?) OR LOWER(emergency_category) = LOWER(?))
        LIMIT ?
        """,
        (guide_id, pet_type, emergency_category, limit),
    ).fetchall()
    results = []
    for row in rows:
        g = row_to_dict(row)
        g["steps"] = json.loads(g.pop("steps_json"))
        g["next_steps"] = json.loads(g.pop("next_steps_json"))
        results.append(g)
    return results


# ---------------------------------------------------------------------------
# Query Helpers — Videos
# ---------------------------------------------------------------------------

def get_video_by_id(conn, video_id):
    """Fetch a single video row by primary key. Returns dict or None."""
    row = conn.execute(
        "SELECT * FROM videos WHERE id = ?", (video_id,)
    ).fetchone()
    return row_to_dict(row)


def get_video_by_guide(conn, guide_id):
    """Return the video linked to a guide, or None."""
    row = conn.execute(
        "SELECT * FROM videos WHERE guide_id = ? AND approved = 1 LIMIT 1",
        (guide_id,),
    ).fetchone()
    return row_to_dict(row)


def get_related_videos(conn, exclude_video_id, limit=3):
    """Return up to `limit` videos excluding the given video id."""
    rows = conn.execute(
        "SELECT * FROM videos WHERE id != ? AND approved = 1 LIMIT ?",
        (exclude_video_id, limit),
    ).fetchall()
    return rows_to_list(rows)


# ---------------------------------------------------------------------------
# Query Helpers — Quizzes
# ---------------------------------------------------------------------------

def get_all_quizzes(conn, pet_type=None):
    """Return all approved quizzes, optionally filtered by pet type."""
    if pet_type:
        rows = conn.execute(
            "SELECT * FROM quizzes WHERE approved = 1 AND pet_type = ? ORDER BY id",
            (pet_type,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM quizzes WHERE approved = 1 ORDER BY id"
        ).fetchall()
    return rows_to_list(rows)


def get_quiz_with_questions(conn, quiz_id):
    """
    Fetch a full quiz dict including its questions and answer options.
    Returns None if the quiz does not exist.

    Returned structure mirrors the original JSON shape so QuizEngine
    requires no changes.
    """
    quiz_row = conn.execute(
        "SELECT * FROM quizzes WHERE id = ? AND approved = 1", (quiz_id,)
    ).fetchone()
    if not quiz_row:
        return None

    quiz = row_to_dict(quiz_row)

    question_rows = conn.execute(
        "SELECT * FROM questions WHERE quiz_id = ? ORDER BY id", (quiz_id,)
    ).fetchall()

    questions = []
    for qrow in question_rows:
        q = row_to_dict(qrow)
        answer_rows = conn.execute(
            "SELECT option_text FROM answers WHERE question_id = ? ORDER BY option_order",
            (q["id"],),
        ).fetchall()
        q["options"] = [r["option_text"] for r in answer_rows]
        questions.append(q)

    quiz["questions"] = questions
    return quiz


# ---------------------------------------------------------------------------
# Query Helpers — Feedback
# ---------------------------------------------------------------------------

def insert_feedback(conn, content_type, content_id, rating, comment):
    """
    Insert a validated feedback record.
    content_type must be 'guide', 'video', or 'quiz'.
    rating must be an integer between 1 and 5.
    comment is optional and truncated to 200 characters.
    Returns the new row id.
    """
    # Enforce application-level constraints as a second safety layer
    assert content_type in ("guide", "video", "quiz"), "Invalid content type"
    rating = int(rating)
    assert 1 <= rating <= 5, "Rating must be between 1 and 5"
    comment = (comment or "").strip()[:200] or None

    cur = conn.execute(
        """
        INSERT INTO feedback (content_type, content_id, rating, comment, submitted_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            content_type,
            int(content_id),
            rating,
            comment,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    return cur.lastrowid


def get_feedback_for_content(conn, content_type, content_id):
    """Return all feedback rows for a given piece of content."""
    rows = conn.execute(
        """
        SELECT * FROM feedback
        WHERE content_type = ? AND content_id = ?
        ORDER BY submitted_at DESC
        """,
        (content_type, int(content_id)),
    ).fetchall()
    return rows_to_list(rows)


def get_all_feedback(conn, limit=100):
    """Return the most recent feedback entries (for admin dashboard)."""
    rows = conn.execute(
        "SELECT * FROM feedback ORDER BY submitted_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return rows_to_list(rows)


def get_average_rating(conn, content_type, content_id):
    """Return the average rating for a content item, or None if no feedback."""
    row = conn.execute(
        """
        SELECT AVG(rating) AS avg_rating, COUNT(*) AS count
        FROM feedback WHERE content_type = ? AND content_id = ?
        """,
        (content_type, int(content_id)),
    ).fetchone()
    if row and row["count"] > 0:
        return round(row["avg_rating"], 1), row["count"]
    return None, 0


# ---------------------------------------------------------------------------
# Query Helpers — Quiz Results
# ---------------------------------------------------------------------------

def insert_quiz_result(conn, quiz_id, score, total, percentage, answers_snapshot):
    """
    Persist a scored quiz result.
    answers_snapshot is a list of per-question result dicts (serialised to JSON).
    Returns the new row id.
    """
    cur = conn.execute(
        """
        INSERT INTO quiz_results
            (quiz_id, score, total, percentage, answers_json, completed_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            int(quiz_id),
            int(score),
            int(total),
            int(percentage),
            json.dumps(answers_snapshot),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Initialisation Entry Point
# ---------------------------------------------------------------------------

def init_db():
    """Create tables and seed from JSON if this is the first run."""
    create_tables()
    seed_database()
