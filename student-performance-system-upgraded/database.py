from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(
        db.String(80),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    students = db.relationship(
        "Student",
        back_populates="owner",
        cascade="all, delete-orphan"
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    # Each student record belongs to one user.
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=True,
        index=True
    )

    owner = db.relationship(
        "User",
        back_populates="students"
    )

    name = db.Column(db.String(100), nullable=False)
    attendance = db.Column(db.Float, nullable=False)
    assignment = db.Column(db.Float, nullable=False)
    internal_marks = db.Column(db.Float, nullable=False)
    previous_marks = db.Column(db.Float, nullable=False)
    study_hours = db.Column(db.Float, nullable=False)
    final_marks = db.Column(db.Float, nullable=True)
    predicted_marks = db.Column(db.Float, nullable=True)

    def score(self):
        return (
            self.final_marks
            if self.final_marks is not None
            else self.predicted_marks
        )

    def risk(self):
        score = self.score()

        if score is None:
            return "Unknown"
        if score < 50:
            return "High Risk"
        if score < 70:
            return "Medium Risk"

        return "Low Risk"