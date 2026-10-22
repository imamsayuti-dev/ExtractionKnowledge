"""Indonesian keyword extraction with bounded input and protected writes."""
import os
import re
import secrets
from functools import lru_cache
from pathlib import Path

import mysql.connector
from flask import (
    Flask, abort, flash, g, redirect, render_template, request, session, url_for,
)
from nltk.tokenize import PunktSentenceTokenizer
from Sastrawi.Stemmer.StemmerFactory import StemmerFactory

from database import connect_database, transaction

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    APP_USERNAME=os.environ.get("APP_USERNAME", "admin"),
    APP_PASSWORD=os.environ.get("APP_PASSWORD", ""),
    MAX_CONTENT_LENGTH=128 * 1024,
    MAX_FORM_MEMORY_SIZE=128 * 1024,
    MAX_FORM_PARTS=10,
    MAX_TEXT_LENGTH=10000,
    MAX_SENTENCES=100,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",
    TRUSTED_HOSTS=[host.strip() for host in os.environ.get(
        "TRUSTED_HOSTS", "localhost,127.0.0.1,[::1]"
    ).split(",") if host.strip()],
)


def read_keyword_map(path):
    mapping = {}
    with open(path, encoding="utf-8") as source:
        for number, line in enumerate(source, 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            category, separator, keywords = line.partition(":")
            values = [word.strip() for word in keywords.split(",") if word.strip()]
            if not separator or not category.strip() or not values:
                raise ValueError(f"Invalid keyword map at line {number}")
            mapping[category.strip()] = values
    return mapping


keyword_map = read_keyword_map(Path(__file__).parent / "static/data/keyword_map.txt")
# Use our bounded cache instead of Sastrawi's unbounded per-word cache.
stemmer = StemmerFactory().create_stemmer().delegatedStemmer
# Untrained Punkt uses punctuation rules without requiring downloaded NLTK data.
sentence_tokenizer = PunktSentenceTokenizer()


@lru_cache(maxsize=8192)
def stem_word(word):
    return stemmer.stem(word)


def normalize(text):
    # Normalize input and phrases identically; preserve words within phrases.
    return tuple(stem_word(word) if len(word) <= 64 else word
                 for word in re.findall(r"[^\W_]+", text.lower()))


normalized_keywords = {
    category: frozenset(filter(None, (normalize(word) for word in words)))
    for category, words in keyword_map.items()
}


def keyword_matches(words, category):
    words = tuple(words)
    return {
        phrase for phrase in normalized_keywords.get(category, ())
        if any(words[index:index + len(phrase)] == phrase
               for index in range(len(words) - len(phrase) + 1))
    }


def classify_category(words):
    counts = {category: len(keyword_matches(words, category))
              for category in normalized_keywords}
    best = max(counts, key=counts.get, default="unknown")
    return best if counts.get(best, 0) else "unknown"


def calculate_accuracy(words, category):
    """Keyword coverage, not statistically measured model accuracy."""
    total = len(normalized_keywords.get(category, ()))
    return len(keyword_matches(words, category)) / total if total else 0.0


def extract_knowledge(text):
    sentences = [sentence.strip() for sentence in sentence_tokenizer.tokenize(text)
                 if sentence.strip()]
    if len(sentences) > app.config["MAX_SENTENCES"]:
        raise ValueError("Maksimal 100 kalimat per permintaan.")
    results = []
    for sentence in sentences:
        words = normalize(sentence)
        category = classify_category(words)
        results.append(dict(sentence=sentence, category=category,
                            accuracy=calculate_accuracy(words, category)))
    return results


def get_db():
    if "db" not in g:
        g.db = connect_database()
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def protect_request():
    password = app.config["APP_PASSWORD"]
    if password:
        auth = request.authorization
        if not (auth and auth.type.lower() == "basic"
                and secrets.compare_digest((auth.username or "").encode(),
                                           app.config["APP_USERNAME"].encode())
                and secrets.compare_digest((auth.password or "").encode(), password.encode())):
            return "Autentikasi diperlukan.", 401, {
                "WWW-Authenticate": 'Basic realm="Extraction Knowledge", charset="UTF-8"'
            }
    elif request.remote_addr not in {"127.0.0.1", "::1"}:
        abort(403, description="Akses jaringan memerlukan APP_PASSWORD.")
    if request.method == "POST":
        supplied = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not expected or not secrets.compare_digest(supplied.encode(), expected.encode()):
            abort(400, description="Token formulir tidak valid. Muat ulang halaman.")


@app.after_request
def security_headers(response):
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self'; font-src 'self'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store"
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


@app.errorhandler(mysql.connector.Error)
def database_error(error):
    app.logger.error("Database operation failed (%s)", type(error).__name__)
    return render_template("error.html", message="Database tidak tersedia. Coba lagi nanti."), 503


@app.route("/")
def index():
    return render_template("index.html")


def insert_extracted_knowledge(results):
    if results:
        with transaction(get_db()) as cursor:
            cursor.executemany(
                "INSERT INTO extracted_knowledge (category, sentence, accuracy) VALUES (%s, %s, %s)",
                [(row["category"], row["sentence"], row["accuracy"]) for row in results],
            )


@app.route("/result", methods=["GET", "POST"])
def result():
    if request.method == "POST":
        text = request.form.get("text", "").strip()
        if not text or len(text) > app.config["MAX_TEXT_LENGTH"]:
            return render_template("error.html", message="Isi teks antara 1 dan 10.000 karakter."), 400
        try:
            results = extract_knowledge(text)
        except ValueError as error:
            return render_template("error.html", message=str(error)), 400
        insert_extracted_knowledge(results)
        return redirect(url_for("result"), code=303)

    selected_category = request.args.get("category", "")
    page = max(1, request.args.get("page", 1, type=int))
    where = " WHERE category = %s" if selected_category else ""
    params = (selected_category,) if selected_category else ()
    with transaction(get_db()) as cursor:
        cursor.execute("SELECT DISTINCT category FROM extracted_knowledge ORDER BY category")
        categories = [row[0] for row in cursor.fetchall()]
        cursor.execute("SELECT COUNT(*) FROM extracted_knowledge" + where, params)
        total = cursor.fetchone()[0]
        pages = max(1, (total + 9) // 10)
        page = min(page, pages)
        # Named columns support both historical schemas (with and without id).
        cursor.execute(
            "SELECT category, sentence, accuracy FROM extracted_knowledge" + where
            + " ORDER BY category, sentence, accuracy LIMIT %s OFFSET %s",
            params + (10, (page - 1) * 10),
        )
        results = [dict(zip(("category", "sentence", "accuracy"), row)) for row in cursor.fetchall()]
    return render_template("result.html", extraction_results=results, categories=categories,
                           selected_category=selected_category, page=page, pages=pages,
                           total=total, can_reset=bool(app.config["APP_PASSWORD"]))


@app.route("/visual")
def visual():
    selected_category = request.args.get("category", "")
    with transaction(get_db()) as cursor:
        cursor.execute("SELECT category, COUNT(*) FROM extracted_knowledge GROUP BY category ORDER BY category")
        counts = dict(cursor.fetchall())
    categories = list(counts)
    if selected_category:
        counts = {name: count for name, count in counts.items() if name == selected_category}
    return render_template("visual.html", counts=counts, categories=categories,
                           selected_category=selected_category, maximum=max(counts.values(), default=1))


@app.route("/reset", methods=["POST"])
def reset():
    if not app.config["APP_PASSWORD"]:
        abort(403, description="Reset memerlukan autentikasi APP_PASSWORD.")
    with transaction(get_db()) as cursor:
        cursor.execute("DELETE FROM extracted_knowledge")
    flash("Data ekstraksi berhasil dihapus.")
    return redirect(url_for("result"), code=303)


if __name__ == "__main__":
    app.run(host="127.0.0.1", debug=False)
