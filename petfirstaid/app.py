"""
Pet Emergency First-Aid Web Application
Assignment 3 - Swinsoft Consulting / Local Veterinary Association
Coding Standard: PEP 8 (Python Enhancement Proposal 8)
Reference: https://peps.python.org/pep-0008/

Storage: SQLite via database.py (petfirstaid.db)
All persistent data (guides, videos, quizzes, feedback, quiz results) is
read from and written to the SQLite database. JSON files in /data/ are used
only as the initial seed source on first run.
"""

import os
from datetime import datetime
from flask import (
    Flask, render_template, request, jsonify, redirect, url_for, session, flash
)

import database as db

# ---------------------------------------------------------------------------
# Application Factory
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = "petfirstaid_secret_key_2024"

# Initialise database on startup (creates tables + seeds from JSON if empty)
db.init_db()


# ---------------------------------------------------------------------------
# SearchEngine  (controller)
# ---------------------------------------------------------------------------

class SearchEngine:
    """
    Handles all search and filtering operations.
    Responsibilities:
      - Accept pet type and/or emergency category to filter guides via DB.
      - Accept keyword input (max 50 chars) and return matching guides.
      - Return up to 10 relevant first-aid guides within defined constraints.
    Collaborators: database.search_guides(), guides table
    """

    MAX_KEYWORD_LENGTH = 50
    MAX_RESULTS = 10

    @staticmethod
    def search(conn, pet_type=None, emergency_category=None, keyword=None):
        """Query the database and return matching guide dicts."""
        return db.search_guides(
            conn,
            pet_type=pet_type,
            emergency_category=emergency_category,
            keyword=keyword,
            max_results=SearchEngine.MAX_RESULTS,
            keyword_max_len=SearchEngine.MAX_KEYWORD_LENGTH,
        )


# ---------------------------------------------------------------------------
# QuizEngine  (controller)
# ---------------------------------------------------------------------------

class QuizEngine:
    """
    Manages the complete quiz attempt lifecycle.
    Responsibilities:
      - Load quiz with all questions and answers from the database.
      - Enforce all-questions-answered rule before submission.
      - Score submission and produce a QuizResult dict.
      - Persist scored result to quiz_results table.
      - Support resume via Flask session.
    Collaborators: database.get_quiz_with_questions(), database.insert_quiz_result()
    """

    @staticmethod
    def get_quiz(conn, quiz_id):
        """Retrieve a full quiz (with questions and answers) by ID."""
        return db.get_quiz_with_questions(conn, quiz_id)

    @staticmethod
    def score_quiz(quiz, user_answers):
        """
        Score user answers against correct answers (StandardScoringStrategy).
        Returns a QuizResult dict with per-question results and explanations.
        """
        results = []
        correct_count = 0

        for question in quiz["questions"]:
            q_id = str(question["id"])
            user_choice = user_answers.get(q_id)

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
            "quiz_id": quiz["id"],
            "quiz_topic": quiz["topic"],
            "pet_type": quiz["pet_type"],
            "score": correct_count,
            "total": total,
            "percentage": percentage,
            "results": results,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }


# ---------------------------------------------------------------------------
# FeedbackManager  (controller)
# ---------------------------------------------------------------------------

class FeedbackManager:
    """
    Coordinates collection, validation, and storage of user feedback.
    Responsibilities:
      - Validate rating (integer 1-5) and comment length (max 200 chars).
      - Store feedback with timestamp via database layer.
      - Retrieve feedback and average ratings for display.
    Collaborators: database.insert_feedback(), database.get_average_rating()
    """

    VALID_CONTENT_TYPES = {"guide", "video", "quiz"}
    MAX_COMMENT_LENGTH = 200

    @staticmethod
    def validate(rating, comment):
        """
        Validate feedback inputs.
        Returns (True, None) on success or (False, error_message) on failure.
        """
        try:
            rating_int = int(rating)
        except (ValueError, TypeError):
            return False, "Rating must be a whole number between 1 and 5."

        if not 1 <= rating_int <= 5:
            return False, "Rating must be between 1 and 5."

        if comment and len(comment) > FeedbackManager.MAX_COMMENT_LENGTH:
            return False, (
                f"Comment must be {FeedbackManager.MAX_COMMENT_LENGTH} "
                "characters or fewer."
            )

        return True, None

    @staticmethod
    def submit(conn, content_type, content_id, rating, comment):
        """Validate and persist a feedback record. Returns new row id."""
        valid, error = FeedbackManager.validate(rating, comment)
        if not valid:
            raise ValueError(error)
        if content_type not in FeedbackManager.VALID_CONTENT_TYPES:
            raise ValueError("Invalid content type.")
        return db.insert_feedback(conn, content_type, content_id, rating, comment)


# ---------------------------------------------------------------------------
# Routes - Home
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Render the home / landing page."""
    with db.get_db() as conn:
        pets = db.get_all_pets(conn)
        categories = db.get_all_categories(conn)
    return render_template("index.html", pets=pets, categories=categories)


# ---------------------------------------------------------------------------
# Routes - Search (Task 1)
# ---------------------------------------------------------------------------

@app.route("/search")
def search():
    """
    Task 1 - Search Emergency Information.
    Accepts GET parameters: pet_type, emergency_category, keyword.
    Queries the SQLite guides table and returns filtered results.
    """
    pet_type = request.args.get("pet_type", "").strip()
    emergency_category = request.args.get("emergency_category", "").strip()
    keyword = request.args.get("keyword", "").strip()

    if len(keyword) > SearchEngine.MAX_KEYWORD_LENGTH:
        keyword = keyword[:SearchEngine.MAX_KEYWORD_LENGTH]

    with db.get_db() as conn:
        pets = db.get_all_pets(conn)
        categories = db.get_all_categories(conn)
        results = SearchEngine.search(
            conn,
            pet_type=pet_type or None,
            emergency_category=emergency_category or None,
            keyword=keyword or None,
        )

    return render_template(
        "search.html",
        results=results,
        pets=pets,
        categories=categories,
        selected_pet=pet_type,
        selected_category=emergency_category,
        keyword=keyword,
        result_count=len(results),
    )


# ---------------------------------------------------------------------------
# Routes - First-Aid Guide (Task 3)
# ---------------------------------------------------------------------------

@app.route("/guide/<int:guide_id>")
def guide(guide_id):
    """
    Task 3 - View First-Aid Instructions.
    Retrieves guide, linked video, alternatives, and average rating from SQLite.
    """
    with db.get_db() as conn:
        selected_guide = db.get_guide_by_id(conn, guide_id)

        if not selected_guide:
            return render_template("404.html"), 404

        linked_video = None
        if selected_guide.get("video_id"):
            linked_video = db.get_video_by_id(conn, selected_guide["video_id"])

        alternatives = db.get_alternative_guides(
            conn,
            guide_id=guide_id,
            pet_type=selected_guide["pet_type"],
            emergency_category=selected_guide["emergency_category"],
        )

        avg_rating, rating_count = db.get_average_rating(conn, "guide", guide_id)

    return render_template(
        "guide.html",
        guide=selected_guide,
        video=linked_video,
        alternatives=alternatives,
        total_steps=len(selected_guide["steps"]),
        avg_rating=avg_rating,
        rating_count=rating_count,
    )


# ---------------------------------------------------------------------------
# Routes - Video (Task 4)
# ---------------------------------------------------------------------------

@app.route("/video/<int:video_id>")
def video(video_id):
    """
    Task 4 - Watch Veterinary Guidance Video.
    Retrieves video metadata and linked guide from SQLite.
    """
    with db.get_db() as conn:
        selected_video = db.get_video_by_id(conn, video_id)

        if not selected_video:
            return render_template("404.html"), 404

        parent_guide = db.get_guide_by_id(conn, selected_video["guide_id"])
        related_videos = db.get_related_videos(conn, exclude_video_id=video_id)
        avg_rating, rating_count = db.get_average_rating(conn, "video", video_id)

    return render_template(
        "video.html",
        video=selected_video,
        guide=parent_guide,
        related_videos=related_videos,
        avg_rating=avg_rating,
        rating_count=rating_count,
    )


# ---------------------------------------------------------------------------
# Routes - Quiz List
# ---------------------------------------------------------------------------

@app.route("/quizzes")
def quiz_list():
    """Display all available quizzes, optionally filtered by pet type."""
    pet_filter = request.args.get("pet_type", "").strip()

    with db.get_db() as conn:
        pets = db.get_all_pets(conn)
        quizzes = db.get_all_quizzes(conn, pet_type=pet_filter or None)

    return render_template(
        "quiz_list.html",
        quizzes=quizzes,
        pets=pets,
        selected_pet=pet_filter,
    )


# ---------------------------------------------------------------------------
# Routes - Take Quiz (Task 5)
# ---------------------------------------------------------------------------

@app.route("/quiz/<int:quiz_id>", methods=["GET"])
def quiz(quiz_id):
    """
    Task 5 - Take Knowledge Quiz (display phase).
    Loads quiz with questions from SQLite. Restores in-progress answers
    from session to support resume functionality.
    """
    with db.get_db() as conn:
        quiz_data = QuizEngine.get_quiz(conn, quiz_id)

    if not quiz_data:
        return render_template("404.html"), 404

    saved_answers = session.get(f"quiz_{quiz_id}_answers", {})

    return render_template(
        "quiz.html",
        quiz=quiz_data,
        saved_answers=saved_answers,
        total_questions=len(quiz_data["questions"]),
    )


@app.route("/quiz/<int:quiz_id>/save", methods=["POST"])
def quiz_save(quiz_id):
    """Auto-save quiz progress to session for resume support."""
    body = request.get_json(silent=True) or {}
    answers = body.get("answers", {})
    session[f"quiz_{quiz_id}_answers"] = answers
    session.modified = True
    return jsonify({"status": "saved", "count": len(answers)})


@app.route("/quiz/<int:quiz_id>/submit", methods=["POST"])
def quiz_submit(quiz_id):
    """
    Task 5 - Submit quiz answers.
    Validates all questions answered, scores the attempt, and persists
    the result to the quiz_results table in SQLite.
    """
    with db.get_db() as conn:
        quiz_data = QuizEngine.get_quiz(conn, quiz_id)

    if not quiz_data:
        return render_template("404.html"), 404

    total_questions = len(quiz_data["questions"])
    user_answers = {}

    for question in quiz_data["questions"]:
        key = str(question["id"])
        value = request.form.get(f"q_{key}")
        if value is not None:
            user_answers[key] = value

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

    quiz_result = QuizEngine.score_quiz(quiz_data, user_answers)

    with db.get_db() as conn:
        db.insert_quiz_result(
            conn,
            quiz_id=quiz_id,
            score=quiz_result["score"],
            total=quiz_result["total"],
            percentage=quiz_result["percentage"],
            answers_snapshot=quiz_result["results"],
        )

    session.pop(f"quiz_{quiz_id}_answers", None)
    return render_template("quiz_result.html", result=quiz_result, quiz_id=quiz_id)


# ---------------------------------------------------------------------------
# Routes - Feedback (Task 6)
# ---------------------------------------------------------------------------

@app.route("/feedback", methods=["GET", "POST"])
def feedback():
    """
    Task 6 - Submit Feedback.
    GET:  Display the feedback form pre-filled from query parameters.
    POST: Validate rating (1-5) and comment (max 200 chars), then store
          the record in the SQLite feedback table with a timestamp.
    """
    if request.method == "POST":
        content_type = request.form.get("content_type", "").strip()
        content_id = request.form.get("content_id", "").strip()
        rating = request.form.get("rating", "").strip()
        comment = request.form.get("comment", "").strip()

        if content_type not in FeedbackManager.VALID_CONTENT_TYPES:
            flash("Invalid content type for feedback.", "danger")
            return redirect(url_for("index"))

        try:
            content_id_int = int(content_id)
            if content_id_int < 1:
                raise ValueError
        except (ValueError, TypeError):
            flash("Invalid content reference.", "danger")
            return redirect(url_for("index"))

        valid, error = FeedbackManager.validate(rating, comment)
        if not valid:
            return render_template(
                "feedback.html",
                error=error,
                content_type=content_type,
                content_id=content_id,
                rating=rating,
                comment=comment,
            )

        with db.get_db() as conn:
            FeedbackManager.submit(conn, content_type, content_id_int, rating, comment)

        flash("Thank you - your feedback has been submitted!", "success")
        return redirect(_feedback_redirect(content_type, content_id_int))

    content_type = request.args.get("content_type", "guide")
    content_id = request.args.get("content_id", "1")
    return render_template(
        "feedback.html",
        error=None,
        content_type=content_type,
        content_id=content_id,
        rating="",
        comment="",
    )


def _feedback_redirect(content_type, content_id):
    """Return the URL to redirect to after successful feedback submission."""
    if content_type == "guide":
        return url_for("guide", guide_id=content_id)
    if content_type == "video":
        return url_for("video", video_id=content_id)
    if content_type == "quiz":
        return url_for("quiz", quiz_id=content_id)
    return url_for("index")


# ---------------------------------------------------------------------------
# Routes - JSON API
# ---------------------------------------------------------------------------

@app.route("/api/guides")
def api_guides():
    """JSON API - return guides filtered by pet_type and/or category."""
    pet_type = request.args.get("pet_type")
    category = request.args.get("category")
    with db.get_db() as conn:
        results = SearchEngine.search(
            conn, pet_type=pet_type, emergency_category=category
        )
    return jsonify(results)


@app.route("/api/pets")
def api_pets():
    """JSON API - return list of supported pet types."""
    with db.get_db() as conn:
        pets = db.get_all_pets(conn)
    return jsonify(pets)


@app.route("/api/feedback/<content_type>/<int:content_id>")
def api_feedback(content_type, content_id):
    """JSON API - return all feedback records for a content item."""
    if content_type not in FeedbackManager.VALID_CONTENT_TYPES:
        return jsonify({"error": "Invalid content type"}), 400
    with db.get_db() as conn:
        rows = db.get_feedback_for_content(conn, content_type, content_id)
    return jsonify(rows)


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
    app.run(debug=True, port=5575)
