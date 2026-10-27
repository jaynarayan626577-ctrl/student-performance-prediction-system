import os
import io
import csv
from functools import wraps

import joblib
import pandas as pd

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, session, send_file
)
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score

from database import db, User, Student


# -------------------- APP CONFIGURATION --------------------

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "change-this-secret-key-before-deployment"
)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///students.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

db.init_app(app)

MODEL_PATH = os.path.join(BASE_DIR, "model.pkl")
CSV_PATH = os.path.join(BASE_DIR, "students.csv")

FEATURES = [
    "attendance",
    "assignment",
    "internal_marks",
    "previous_marks",
    "study_hours"
]


# -------------------- MODEL FUNCTIONS --------------------

def train_model_from_database():
    """
    Train using the sample CSV, or records with final marks.
    This does not modify student records.
    """
    data = None

    if os.path.exists(CSV_PATH):
        try:
            sample = pd.read_csv(CSV_PATH)
            if all(c in sample.columns for c in FEATURES + ["final_marks"]):
                sample = sample.dropna(subset=FEATURES + ["final_marks"])
                if len(sample) >= 5:
                    data = sample
        except Exception:
            data = None

    if data is None:
        rows = Student.query.filter(
            Student.final_marks.isnot(None)
        ).all()

        if len(rows) < 5:
            raise RuntimeError(
                "Model training needs at least 5 records with final marks "
                "in students.csv or the database."
            )

        data = pd.DataFrame([
            {
                **{k: getattr(s, k) for k in FEATURES},
                "final_marks": s.final_marks
            }
            for s in rows
        ])

    X = data[FEATURES].astype(float)
    y = data["final_marks"].astype(float)

    if len(data) >= 8:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )
        model = RandomForestRegressor(
            n_estimators=200, random_state=42
        )
        model.fit(X_train, y_train)

        predictions = model.predict(X_test)
        mae = mean_absolute_error(y_test, predictions)
        r2 = r2_score(y_test, predictions) if len(y_test) > 1 else 0
    else:
        model = RandomForestRegressor(
            n_estimators=200, random_state=42
        )
        model.fit(X, y)
        mae, r2 = 0.0, 0.0

    joblib.dump(model, MODEL_PATH)
    return mae, r2


def load_model():
    if not os.path.exists(MODEL_PATH):
        train_model_from_database()
    return joblib.load(MODEL_PATH)


def predict_score(values):
    model = load_model()
    frame = pd.DataFrame([values], columns=FEATURES)
    score = float(model.predict(frame)[0])
    return round(max(0, min(100, score)), 2)


def risk_for(score):
    if score is None:
        return "Unknown"
    if score < 50:
        return "High Risk"
    if score < 70:
        return "Medium Risk"
    return "Low Risk"


def warning_for(score):
    if score is None:
        return "No prediction available"
    if score < 50:
        return "Immediate Support Required"
    if score < 70:
        return "Regular Monitoring Required"
    return "Performing Well"


# -------------------- LOGIN PROTECTION --------------------

def logged_in_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def get_owned_student(student_id):
    """Only return a record owned by the currently logged-in user."""
    return Student.query.filter_by(
        id=student_id,
        user_id=session["user_id"]
    ).first_or_404()


@app.context_processor
def inject_helpers():
    return {
        "risk_for": risk_for,
        "warning_for": warning_for
    }


# -------------------- REGISTER --------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(username) < 3:
            flash("Username must contain at least 3 characters.", "danger")
            return render_template("register.html")

        if len(password) < 8:
            flash("Password must contain at least 8 characters.", "danger")
            return render_template("register.html")

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("register.html")

        if User.query.filter_by(username=username).first():
            flash("Username already exists. Choose another.", "danger")
            return render_template("register.html")

        user = User(username=username)
        user.set_password(password)

        try:
            db.session.add(user)
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("Could not create account. Please try again.", "danger")
            return render_template("register.html")

        flash("Account created successfully. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


# -------------------- LOGIN --------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            session.clear()
            session["user_id"] = user.id
            session["username"] = user.username

            next_url = request.args.get("next", "")
            if next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)

            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "danger")

    return render_template("login.html")


# -------------------- LOGOUT --------------------

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# -------------------- HOME --------------------

@app.route("/")
@logged_in_required
def home():
    return render_template("index.html")


# -------------------- DASHBOARD --------------------

@app.route("/dashboard")
@logged_in_required
def dashboard():
    students = Student.query.filter_by(
        user_id=session["user_id"]
    ).order_by(Student.id.desc()).all()

    scores = [
        s.score() for s in students
        if s.score() is not None
    ]

    average_marks = (
        round(sum(scores) / len(scores), 2) if scores else 0
    )

    high_risk = sum(
        1 for s in students if s.risk() == "High Risk"
    )
    medium_risk = sum(
        1 for s in students if s.risk() == "Medium Risk"
    )
    low_risk = sum(
        1 for s in students if s.risk() == "Low Risk"
    )

    return render_template(
        "dashboard.html",
        students=students,
        total_students=len(students),
        average_marks=average_marks,
        high_risk=high_risk,
        medium_risk=medium_risk,
        low_risk=low_risk
    )


# -------------------- PREDICT --------------------

@app.route("/predict", methods=["GET", "POST"])
@logged_in_required
def predict():
    if request.method == "GET":
        return redirect(url_for("home"))

    try:
        name = request.form.get("name", "").strip()
        if not name:
            raise ValueError("Student name is required.")

        values = {
            k: float(request.form[k])
            for k in FEATURES
        }

        for key, value in values.items():
            if not 0 <= value <= 100 and key != "study_hours":
                raise ValueError(f"{key} must be between 0 and 100.")

        if values["study_hours"] < 0:
            raise ValueError("Study hours cannot be negative.")

        prediction = predict_score(values)

        student = Student(
            name=name,
            user_id=session["user_id"],
            **values,
            predicted_marks=prediction
        )

        db.session.add(student)
        db.session.commit()

        flash("Prediction saved successfully.", "success")

        return render_template(
            "result.html",
            student=student,
            prediction=prediction,
            risk=risk_for(prediction),
            message=warning_for(prediction)
        )

    except Exception as exc:
        db.session.rollback()
        flash(f"Could not save prediction: {exc}", "danger")
        return redirect(url_for("home"))


# -------------------- ADD STUDENT --------------------

@app.route("/students/add", methods=["GET", "POST"])
@logged_in_required
def add_student():
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            if not name:
                raise ValueError("Student name is required.")

            values = {
                k: float(request.form[k])
                for k in FEATURES
            }

            for key, value in values.items():
                if key != "study_hours" and not 0 <= value <= 100:
                    raise ValueError(f"{key} must be between 0 and 100.")

            if values["study_hours"] < 0:
                raise ValueError("Study hours cannot be negative.")

            final_raw = request.form.get("final_marks", "").strip()
            final_marks = float(final_raw) if final_raw else None

            if final_marks is not None and not 0 <= final_marks <= 100:
                raise ValueError("Final marks must be between 0 and 100.")

            predicted = predict_score(values)

            student = Student(
                name=name,
                user_id=session["user_id"],
                **values,
                final_marks=final_marks,
                predicted_marks=predicted
            )

            db.session.add(student)
            db.session.commit()

            flash("Student added successfully.", "success")
            return redirect(url_for("dashboard"))

        except Exception as exc:
            db.session.rollback()
            flash(f"Please check the values. {exc}", "danger")

    return render_template(
        "student_form.html",
        student=None,
        title="Add Student"
    )


# -------------------- EDIT STUDENT --------------------

@app.route("/students/<int:student_id>/edit", methods=["GET", "POST"])
@logged_in_required
def edit_student(student_id):
    student = get_owned_student(student_id)

    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            if not name:
                raise ValueError("Student name is required.")

            student.name = name

            for key in FEATURES:
                value = float(request.form[key])
                if key != "study_hours" and not 0 <= value <= 100:
                    raise ValueError(f"{key} must be between 0 and 100.")
                if key == "study_hours" and value < 0:
                    raise ValueError("Study hours cannot be negative.")
                setattr(student, key, value)

            final_raw = request.form.get("final_marks", "").strip()
            student.final_marks = float(final_raw) if final_raw else None

            if (
                student.final_marks is not None
                and not 0 <= student.final_marks <= 100
            ):
                raise ValueError("Final marks must be between 0 and 100.")

            student.predicted_marks = predict_score({
                key: getattr(student, key) for key in FEATURES
            })

            db.session.commit()
            flash("Student updated successfully.", "success")
            return redirect(url_for("dashboard"))

        except Exception as exc:
            db.session.rollback()
            flash(f"Could not update student: {exc}", "danger")

    return render_template(
        "student_form.html",
        student=student,
        title="Edit Student"
    )


# -------------------- DELETE STUDENT --------------------

@app.post("/students/<int:student_id>/delete")
@logged_in_required
def delete_student(student_id):
    student = get_owned_student(student_id)

    db.session.delete(student)
    db.session.commit()

    flash("Student deleted successfully.", "success")
    return redirect(url_for("dashboard"))


# -------------------- STUDENT DETAILS --------------------

@app.route("/students/<int:student_id>")
@logged_in_required
def student_detail(student_id):
    student = get_owned_student(student_id)
    return render_template("student_detail.html", student=student)


# -------------------- CSV IMPORT --------------------

@app.route("/import", methods=["GET", "POST"])
@logged_in_required
def import_students():
    if request.method == "POST":
        file = request.files.get("file")

        if not file or not file.filename:
            flash("Please choose a CSV file.", "danger")
            return redirect(url_for("import_students"))

        try:
            data = pd.read_csv(file)

            required = {"name", *FEATURES}
            missing = required - set(data.columns)

            if missing:
                raise ValueError(
                    "Missing columns: " + ", ".join(sorted(missing))
                )

            added = 0

            for _, row in data.iterrows():
                values = {
                    k: float(row[k]) for k in FEATURES
                }

                final = (
                    float(row["final_marks"])
                    if "final_marks" in data.columns
                    and pd.notna(row["final_marks"])
                    else None
                )

                predicted = predict_score(values)

                student = Student(
                    name=str(row["name"]).strip(),
                    user_id=session["user_id"],
                    **values,
                    final_marks=final,
                    predicted_marks=predicted
                )

                db.session.add(student)
                added += 1

            db.session.commit()
            flash(f"{added} students imported successfully.", "success")
            return redirect(url_for("dashboard"))

        except Exception as exc:
            db.session.rollback()
            flash(f"Import failed: {exc}", "danger")

    return render_template("import.html")


# -------------------- CSV EXPORT --------------------

@app.route("/export")
@logged_in_required
def export_students():
    students = Student.query.filter_by(
        user_id=session["user_id"]
    ).order_by(Student.id).all()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "id", "name", *FEATURES,
        "final_marks", "predicted_marks", "risk"
    ])

    for student in students:
        writer.writerow([
            student.id,
            student.name,
            *[getattr(student, key) for key in FEATURES],
            student.final_marks,
            student.predicted_marks,
            student.risk()
        ])

    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="student_performance_export.csv"
    )


# -------------------- TRAIN MODEL --------------------

@app.route("/train", methods=["POST"])
@logged_in_required
def retrain():
    try:
        mae, r2 = train_model_from_database()
        flash(
            f"Model trained. MAE: {mae:.2f}, R²: {r2:.2f}",
            "success"
        )
    except Exception as exc:
        flash(f"Model training failed: {exc}", "danger")

    return redirect(url_for("dashboard"))


# -------------------- MODEL INFORMATION --------------------

@app.route("/model")
@logged_in_required
def model_info():
    students = Student.query.filter_by(
        user_id=session["user_id"]
    ).filter(
        Student.final_marks.isnot(None)
    ).count()

    return render_template(
        "model.html",
        training_students=students,
        model_file=os.path.exists(MODEL_PATH)
    )


# -------------------- START APP --------------------

if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    app.run(debug=True)