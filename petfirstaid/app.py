"""
Pet Emergency First-Aid Web Application
Assignment 3 - Swinsoft Consulting / Local Veterinary Association
Coding Standard: PEP 8 (Python Enhancement Proposal 8)
Reference: https://peps.python.org/pep-0008/
"""

import json
import os
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, session

# ---------------------------------------------------------------------------
# Application Factory
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = "petfirstaid_secret_key_2024"

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


# ---------------------------------------------------------------------------
# Data Access Layer  (replaces a database for this demo)
# ---------------------------------------------------------------------------

def load_json(filename):
    """Load and return parsed JSON from the data directory."""
    path = os.path.join(DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(filename, data):
    """Serialise data to JSON and write to the data directory."""
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# SearchEngine  (controller)
# ---------------------------------------------------------------------------

class SearchEngine:
    """
    Handles all search and filtering operations.
    Responsibilities:
      - Accept pet type and/or emergency category to filter guides.
      - Accept keyword input (max 50 chars) for text-based search.
      - Return matching FirstAidGuide records within defined constraints.
    Collaborators: guides.json (FirstAidGuide data)
    """

    MAX_KEYWORD_LENGTH = 50
    MAX_RESULTS = 10
    MIN_RESULTS = 3

    @staticmethod
    def search(pet_type=None, emergency_category=None, keyword=None):
        """Return matching guides based on pet type, category, or keyword."""
        guides = load_json("guides.json")["guides"]
        results = []

        keyword = (keyword or "").strip()[:SearchEngine.MAX_KEYWORD_LENGTH].lower()

        for guide in guides:
            match = True

            if pet_type and guide["pet_type"].lower() != pet_type.lower():
                match = False

            if emergency_category and guide["emergency_category"].lower() != emergency_category.lower():
                match = False

            if keyword and match:
                searchable = (
                    guide["title"] + " " +
                    guide["summary"] + " " +
                    guide["pet_type"] + " " +
                    guide["emergency_category"]
                ).lower()
                if keyword not in searchable:
                    match = False

            if match:
                results.append(guide)

        return results[:SearchEngine.MAX_RESULTS]


# ---------------------------------------------------------------------------
# QuizEngine  (controller)
# ---------------------------------------------------------------------------

class QuizEngine:
    """
    Manages the complete quiz attempt lifecycle.
    Responsibilities:
      - Load quiz questions.
      - Enforce all-questions-answered rule before submission.
      - Score submission and produce a QuizResult.
      - Support resume via session storage.
    Collaborators: quizzes.json, session (QuizResult data)
    """

    @staticmethod
    def get_quiz(quiz_id):
        """Retrieve a quiz by its ID."""
        quizzes = load_json("quizzes.json")
        for quiz in quizzes:
            if quiz["id"] == quiz_id:
                return quiz
        return None

    @staticmethod
    def score_quiz(quiz, user_answers):
        """
        Score user answers against correct answers.
        Returns a QuizResult dict containing score, per-question results,
        and explanations (StandardScoringStrategy).
        """
        results = []
        correct_count = 0

        for question in quiz["questions"]:
            q_id = str(question["id"])
            user_choice = user_answers.get(q_id)

            # Validate answer index
            if user_choice is not None:
                try:
                    user_choice = int(user_choice)
                except (ValueError, TypeError):
                    user_choice = None

            is_correct = (user_choice == question["correct"])
            if is_correct:
                correct_count += 1

            results.append({
                "question_text": question["text"],
                "options": question["options"],
                "user_choice": user_choice,
                "correct_answer": question["correct"],
                "is_correct": is_correct,
                "explanation": question["explanation"],
            })

        total = len(quiz["questions"])
        percentage = round((correct_count / total) * 100) if total > 0 else 0

        return {
            "quiz_topic": quiz["topic"],
            "pet_type": quiz["pet_type"],
            "score": correct_count,
            "total": total,
            "percentage": percentage,
            "results": results,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }


# ---------------------------------------------------------------------------
# Routes — Home
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Render the home / landing page."""
    data = load_json("guides.json")
    return render_template(
        "index.html",
        pets=data["pets"],
        categories=data["emergency_categories"],
    )


# ---------------------------------------------------------------------------
# Routes — Search (Task 1)
# ---------------------------------------------------------------------------

@app.route("/search")
def search():
    """
    Task 1 — Search Emergency Information.
    Accepts GET parameters: pet_type, emergency_category, keyword.
    Returns filtered guide results.
    """
    data = load_json("guides.json")
    pet_type = request.args.get("pet_type", "").strip()
    emergency_category = request.args.get("emergency_category", "").strip()
    keyword = request.args.get("keyword", "").strip()

    # Validate keyword length (boundary condition)
    if len(keyword) > SearchEngine.MAX_KEYWORD_LENGTH:
        keyword = keyword[:SearchEngine.MAX_KEYWORD_LENGTH]

    results = SearchEngine.search(
        pet_type=pet_type or None,
        emergency_category=emergency_category or None,
        keyword=keyword or None,
    )

    return render_template(
        "search.html",
        results=results,
        pets=data["pets"],
        categories=data["emergency_categories"],
        selected_pet=pet_type,
        selected_category=emergency_category,
        keyword=keyword,
        result_count=len(results),
    )


# ---------------------------------------------------------------------------
# Routes — First-Aid Guide (Task 3)
# ---------------------------------------------------------------------------

@app.route("/guide/<int:guide_id>")
def guide(guide_id):
    """
    Task 3 — View First-Aid Instructions.
    Retrieves and displays a single guide with steps, warnings,
    next-step recommendations, and linked video.
    """
    guides = load_json("guides.json")["guides"]
    videos = load_json("videos.json")

    selected_guide = next((g for g in guides if g["id"] == guide_id), None)

    if not selected_guide:
        return render_template("404.html"), 404

    # Retrieve linked video if present
    linked_video = None
    if selected_guide.get("video_id"):
        linked_video = next(
            (v for v in videos if v["id"] == selected_guide["video_id"]),
            None,
        )

    # Build alternative guide suggestions (same pet or same category)
    alternatives = [
        g for g in guides
        if g["id"] != guide_id and (
            g["pet_type"] == selected_guide["pet_type"] or
            g["emergency_category"] == selected_guide["emergency_category"]
        )
    ][:3]

    return render_template(
        "guide.html",
        guide=selected_guide,
        video=linked_video,
        alternatives=alternatives,
        total_steps=len(selected_guide["steps"]),
    )


# ---------------------------------------------------------------------------
# Routes — Video (Task 4)
# ---------------------------------------------------------------------------

@app.route("/video/<int:video_id>")
def video(video_id):
    """
    Task 4 — Watch Veterinary Guidance Video.
    Displays an embedded video player with related guides and resources.
    """
    videos = load_json("videos.json")
    guides = load_json("guides.json")["guides"]

    selected_video = next((v for v in videos if v["id"] == video_id), None)

    if not selected_video:
        return render_template("404.html"), 404

    # Retrieve parent guide
    parent_guide = next(
        (g for g in guides if g["id"] == selected_video["guide_id"]),
        None,
    )

    # Related videos (other videos, max 3)
    related_videos = [v for v in videos if v["id"] != video_id][:3]

    return render_template(
        "video.html",
        video=selected_video,
        guide=parent_guide,
        related_videos=related_videos,
    )


# ---------------------------------------------------------------------------
# Routes — Quiz List
# ---------------------------------------------------------------------------

@app.route("/quizzes")
def quiz_list():
    """Display all available quizzes, filterable by pet type."""
    quizzes = load_json("quizzes.json")
    data = load_json("guides.json")
    pet_filter = request.args.get("pet_type", "").strip()

    if pet_filter:
        quizzes = [q for q in quizzes if q["pet_type"] == pet_filter]

    return render_template(
        "quiz_list.html",
        quizzes=quizzes,
        pets=data["pets"],
        selected_pet=pet_filter,
    )


# ---------------------------------------------------------------------------
# Routes — Take Quiz (Task 5)
# ---------------------------------------------------------------------------

@app.route("/quiz/<int:quiz_id>", methods=["GET"])
def quiz(quiz_id):
    """
    Task 5 — Take Knowledge Quiz (display phase).
    Loads quiz questions. Restores in-progress answers from session.
    """
    quiz_data = QuizEngine.get_quiz(quiz_id)

    if not quiz_data:
        return render_template("404.html"), 404

    # Restore saved answers from session (resume functionality)
    saved_answers = session.get(f"quiz_{quiz_id}_answers", {})

    return render_template(
        "quiz.html",
        quiz=quiz_data,
        saved_answers=saved_answers,
        total_questions=len(quiz_data["questions"]),
    )


@app.route("/quiz/<int:quiz_id>/save", methods=["POST"])
def quiz_save(quiz_id):
    """
    Auto-save quiz progress to session so the user can resume later.
    Accepts JSON body: { "answers": { "1": 2, "2": 0, ... } }
    """
    body = request.get_json(silent=True) or {}
    answers = body.get("answers", {})

    # Persist to session
    session[f"quiz_{quiz_id}_answers"] = answers
    session.modified = True

    return jsonify({"status": "saved", "count": len(answers)})


@app.route("/quiz/<int:quiz_id>/submit", methods=["POST"])
def quiz_submit(quiz_id):
    """
    Task 5 — Submit quiz answers.
    Validates all questions answered before scoring.
    Returns scored QuizResult.
    """
    quiz_data = QuizEngine.get_quiz(quiz_id)

    if not quiz_data:
        return render_template("404.html"), 404

    total_questions = len(quiz_data["questions"])
    user_answers = {}

    for question in quiz_data["questions"]:
        key = str(question["id"])
        value = request.form.get(f"q_{key}")
        if value is not None:
            user_answers[key] = value

    # Validate all questions answered (boundary condition)
    if len(user_answers) < total_questions:
        saved_answers = {k: int(v) for k, v in user_answers.items()}
        session[f"quiz_{quiz_id}_answers"] = saved_answers

        error = f"Please answer all {total_questions} questions before submitting."
        return render_template(
            "quiz.html",
            quiz=quiz_data,
            saved_answers=saved_answers,
            total_questions=total_questions,
            error=error,
        )

    # Score the quiz
    quiz_result = QuizEngine.score_quiz(quiz_data, user_answers)

    # Clear saved progress after successful submission
    session.pop(f"quiz_{quiz_id}_answers", None)

    return render_template("quiz_result.html", result=quiz_result, quiz_id=quiz_id)


# ---------------------------------------------------------------------------
# Routes — API Endpoints (JSON)
# ---------------------------------------------------------------------------

@app.route("/api/guides")
def api_guides():
    """JSON API — return guides filtered by pet_type and/or category."""
    pet_type = request.args.get("pet_type")
    category = request.args.get("category")
    results = SearchEngine.search(pet_type=pet_type, emergency_category=category)
    return jsonify(results)


@app.route("/api/pets")
def api_pets():
    """JSON API — return list of supported pet types."""
    data = load_json("guides.json")
    return jsonify(data["pets"])


# ---------------------------------------------------------------------------
# Error Handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(500)
def server_error(e):
    return render_template("500.html"), 500


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, port=5000)
