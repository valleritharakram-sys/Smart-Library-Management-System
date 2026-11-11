from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Book(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  title = db.Column(db.String(150), nullable=False)
  author = db.Column(db.String(100), nullable=False)
  isbn = db.Column(db.String(20), unique=True, nullable=False)
  category = db.Column(db.String(80), default='Software Engineering')
  total_copies = db.Column(db.Integer, default=1)
  available_copies = db.Column(db.Integer, default=1)

  @property
  def average_rating(self):
    if not self.reviews:
      return 4.9
    return round(sum(r.rating for r in self.reviews) / len(self.reviews), 1)

  @property
  def review_count(self):
    return len(self.reviews)


class Member(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  name = db.Column(db.String(100), nullable=False)
  roll_number = db.Column(db.String(50), unique=True, nullable=False)
  email = db.Column(db.String(120), unique=True, nullable=False)
  phone = db.Column(db.String(20), nullable=False)

  @property
  def active_loans(self):
    return [loan for loan in self.loans if loan.status == 'ACTIVE']

  @property
  def total_unpaid_fines(self):
    return sum(loan.fine_amount for loan in self.loans if loan.fine_status == 'UNPAID')


class Loan(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
  member_id = db.Column(db.Integer, db.ForeignKey('member.id'), nullable=False)
  borrowed_date = db.Column(db.DateTime, default=datetime.utcnow)
  due_date = db.Column(
      db.DateTime, default=lambda: datetime.utcnow() + timedelta(days=14)
  )
  returned_date = db.Column(db.DateTime, nullable=True)
  status = db.Column(db.String(20), default='ACTIVE')  # ACTIVE or RETURNED
  fine_amount = db.Column(db.Float, default=0.0)
  fine_status = db.Column(db.String(20), default='NONE')  # NONE, UNPAID, PAID, WAIVED
  fine_reason = db.Column(db.String(200), nullable=True)
  processed_by = db.Column(db.String(100), nullable=True)  # Name of incharge who processed return/fine

  book = db.relationship('Book', backref='loans')
  member = db.relationship('Member', backref='loans')

  @property
  def days_remaining(self):
    """Days left until due date (negative = overdue)."""
    from datetime import datetime
    if self.status != 'ACTIVE':
      return None
    return (self.due_date - datetime.utcnow()).days

  @property
  def is_overdue(self):
    now = datetime.utcnow()
    target = self.returned_date if (self.status == 'RETURNED' and self.returned_date) else now
    return target > self.due_date

  @property
  def overdue_days(self):
    now = datetime.utcnow()
    target = self.returned_date if (self.status == 'RETURNED' and self.returned_date) else now
    if target > self.due_date:
      return (target - self.due_date).days or 1
    return 0

  @property
  def suggested_fine(self):
    return round(self.overdue_days * 10.0, 2)  # ₹10.00 per day


class Reservation(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
  member_id = db.Column(db.Integer, db.ForeignKey('member.id'), nullable=False)
  reserved_date = db.Column(db.DateTime, default=datetime.utcnow)
  notified_date = db.Column(db.DateTime, nullable=True)
  status = db.Column(db.String(25), default='PENDING')  # PENDING, READY_FOR_PICKUP, FULFILLED, CANCELLED

  book = db.relationship('Book', backref='reservations')
  member = db.relationship('Member', backref='reservations')


class Incharge(db.Model):
  """Library In-Charge model. Maximum of 2 accounts allowed in system."""
  id = db.Column(db.Integer, primary_key=True)
  username = db.Column(db.String(50), unique=True, nullable=False)
  name = db.Column(db.String(100), nullable=False)
  password_hash = db.Column(db.String(255), nullable=False)
  role = db.Column(db.String(50), default='Library In-Charge')
  email = db.Column(db.String(120), nullable=True)
  phone = db.Column(db.String(20), nullable=True)
  last_login = db.Column(db.DateTime, nullable=True)

  def set_password(self, password):
    from werkzeug.security import generate_password_hash
    self.password_hash = generate_password_hash(password)

  def check_password(self, password):
    from werkzeug.security import check_password_hash
    return check_password_hash(self.password_hash, password)


class Review(db.Model):
  """Student Book Reviews & Ratings."""
  id = db.Column(db.Integer, primary_key=True)
  book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
  student_name = db.Column(db.String(100), nullable=False)
  roll_number = db.Column(db.String(50), nullable=False)
  rating = db.Column(db.Integer, default=5)  # 1 to 5
  comment = db.Column(db.Text, nullable=False)
  created_at = db.Column(db.DateTime, default=datetime.utcnow)

  book = db.relationship('Book', backref=db.backref('reviews', lazy=True, order_by='Review.created_at.desc()'))

