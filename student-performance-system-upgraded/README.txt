STUDENT PERFORMANCE PREDICTION & EARLY WARNING SYSTEM

This upgraded version uses SQLite so students are managed through the website. You do not need to edit Python/HTML to add students later.

FEATURES
- Teacher/Admin login
- SQLite database
- Automatic import of the original students.csv on first run
- Add student from website
- Edit student from website
- Delete student from website
- Predict and save student
- Bulk CSV import for many students
- Search students
- Risk classification
- Early warning messages
- Dashboard charts
- CSV export
- Model retraining from saved actual final marks
- Responsive UI

FIRST RUN
1. Open this folder in VS Code.
2. Open Terminal.
3. Run:
   python -m pip install -r requirements.txt
4. Run:
   python app.py
5. Open the local Flask address shown in the terminal, normally http://127.0.0.1:5000
6. Login:
   Username: admin
   Password: admin123

IMPORTANT
- students.db is created automatically inside the instance folder.
- The original students.csv is imported automatically only when the database is empty.
- After that, use Add Student / Bulk Import / Edit / Delete from the website.
- To train the model again, enter actual final marks and click Retrain Model.
