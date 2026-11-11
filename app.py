from datetime import datetime, timedelta
from functools import wraps
import csv
import io
import re
import random
from markupsafe import Markup, escape
from flask import Flask, Response, flash, jsonify, redirect, render_template, request, session, url_for
from models import Book, db, Incharge, Loan, Member, Reservation, Review
from search_engine import ai_search, get_search_suggestions, gemini_interpret_query

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///library.db'
app.config['SECRET_KEY'] = 'dev-key-for-sessions'
db.init_app(app)


# ── Access Control Decorator: Only In-Charge Allowed ───────────────────────────
def incharge_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'incharge_id' not in session:
            flash(
                '🔒 Restricted Access: Only an authorized In-Charge can mark books returned, assess penalties, or mark fines as PAID.',
                'warning',
            )
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


# ── Helper: Mandatory 10-Digit Phone Number Validator ─────────────────────────
def validate_and_clean_phone(phone_str):
    """
    Cleans phone string and verifies it is strictly mandatory and exactly 10 digits.
    Supports +91 or leading 0 stripping.
    Returns cleaned 10-digit string or None.
    """
    if not phone_str:
        return None
    cleaned = re.sub(r'\D', '', str(phone_str).strip())
    if len(cleaned) == 12 and cleaned.startswith('91'):
        cleaned = cleaned[2:]
    elif len(cleaned) == 11 and cleaned.startswith('0'):
        cleaned = cleaned[1:]
    if len(cleaned) == 10 and cleaned.isdigit():
        return cleaned
    return None


# ── Jinja2 custom filter: highlight search terms in text ───────────────────────
@app.template_filter('highlight')
def highlight_filter(text, query):
    if not query or not text:
        return escape(text)
    escaped_text = str(escape(text))
    # Highlight each word in the query
    for word in re.findall(r'\w{2,}', query):
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        escaped_text = pattern.sub(
            lambda m: f'<mark class="search-hl">{m.group()}</mark>',
            escaped_text
        )
    return Markup(escaped_text)


# ── API: Real-time autocomplete suggestions ─────────────────────────────────────
@app.route('/api/search/suggest')
def search_suggest():
    partial = request.args.get('q', '').strip()
    all_books = Book.query.all()
    suggestions = get_search_suggestions(all_books, partial, limit=8)
    return jsonify(suggestions)


# ── In-Charge Authentication & Session Management ──────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    next_url = request.args.get('next', '')
    incharges = Incharge.query.order_by(Incharge.id.asc()).all()

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        incharge = Incharge.query.filter_by(username=username).first()
        if incharge and incharge.check_password(password):
            session['incharge_id'] = incharge.id
            session['incharge_username'] = incharge.username
            session['incharge_name'] = incharge.name
            session['incharge_role'] = incharge.role
            incharge.last_login = datetime.utcnow()
            db.session.commit()

            flash(f'Welcome, {incharge.name}! You are authenticated as {incharge.role}.', 'success')
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid In-Charge credentials. Please check your username and password.', 'danger')

    return render_template('login.html', incharges=incharges, next_url=next_url)


@app.route('/logout')
def logout():
    incharge_name = session.pop('incharge_name', None)
    session.pop('incharge_id', None)
    session.pop('incharge_username', None)
    session.pop('incharge_role', None)
    if incharge_name:
        flash(f'Signed out successfully from In-Charge session ({incharge_name}).', 'info')
    else:
        flash('You have been signed out.', 'info')
    return redirect(url_for('catalog'))


# ── In-Charge Management (Strict Maximum of 2 In-Charges) ───────────────────────
@app.route('/admin/incharges/add', methods=['POST'])
@incharge_required
def add_incharge():
    current_count = Incharge.query.count()
    if current_count >= 2:
        flash('🚫 Limit Reached: Maximum of 2 In-Charge accounts allowed in the system. Cannot add more.', 'danger')
        return redirect(url_for('dashboard'))

    username = request.form.get('username', '').strip().lower()
    name = request.form.get('name', '').strip()
    password = request.form.get('password', '')
    email = request.form.get('email', '').strip()
    phone_raw = request.form.get('phone', '').strip()
    role = request.form.get('role', 'Library In-Charge').strip()

    if not username or not password or not name:
        flash('All required fields must be filled.', 'warning')
        return redirect(url_for('dashboard'))

    phone = ''
    if phone_raw:
        phone = validate_and_clean_phone(phone_raw)
        if not phone:
            flash('Invalid In-Charge Phone: Phone number must be exactly 10 digits.', 'warning')
            return redirect(url_for('dashboard'))

    if Incharge.query.filter_by(username=username).first():
        flash(f'Username "{username}" is already in use.', 'warning')
        return redirect(url_for('dashboard'))

    new_inc = Incharge(username=username, name=name, email=email, phone=phone, role=role)
    new_inc.set_password(password)
    db.session.add(new_inc)
    db.session.commit()

    flash(f'Added In-Charge account #{current_count + 1} ({name}) successfully. System quota: {current_count + 1}/2.', 'success')
    return redirect(url_for('dashboard'))


# ── Catalog route with AI-powered search ───────────────────────────────────────
@app.route('/')
def catalog():
    search_query = request.args.get('q', '').strip()
    selected_category = request.args.get('category', '').strip()

    all_books = Book.query.all()

    # Category pre-filter
    if selected_category and selected_category != 'All':
        pool = [b for b in all_books if b.category == selected_category]
    else:
        pool = list(all_books)

    # AI-powered search
    ai_intent = None
    suggestions = []
    expanded_terms = []
    gemini_rewrite = None

    if search_query:
        # Try Gemini LLM interpretation first (only if API key set)
        book_titles = [b.title for b in all_books]
        gemini_rewrite = gemini_interpret_query(search_query, book_titles)
        effective_query = gemini_rewrite if gemini_rewrite else search_query

        books, suggestions, ai_intent, expanded_terms = ai_search(pool, effective_query)
    else:
        books = sorted(pool, key=lambda b: b.title)

    # Category metadata
    categories = sorted(list({b.category for b in all_books if b.category}))

    # Category stats: {category: {total, available}}
    cat_stats = {}
    for b in all_books:
        if b.category:
            if b.category not in cat_stats:
                cat_stats[b.category] = {'total': 0, 'available': 0}
            cat_stats[b.category]['total'] += b.total_copies
            cat_stats[b.category]['available'] += b.available_copies

    # Borrow count per book (popularity)
    borrow_counts = {b.id: len(b.loans) for b in all_books}

    # Most popular books (top 3 by borrow count)
    popular_books = sorted(
        [b for b in all_books if len(b.loans) > 0],
        key=lambda b: len(b.loans),
        reverse=True
    )[:3]

    # Book of the Day — seed with today's date
    today_seed = int(datetime.utcnow().strftime('%Y%m%d'))
    rng = random.Random(today_seed)
    featured_book = rng.choice(all_books) if all_books else None

    members = Member.query.order_by(Member.roll_number.asc()).all()
    return render_template(
        'index.html',
        books=books,
        members=members,
        search_query=search_query,
        categories=categories,
        selected_category=selected_category,
        featured_book=featured_book,
        cat_stats=cat_stats,
        borrow_counts=borrow_counts,
        popular_books=popular_books,
        today=datetime.utcnow(),
        ai_intent=ai_intent,
        suggestions=suggestions,
        expanded_terms=expanded_terms,
        gemini_rewrite=gemini_rewrite,
        total_books=len(all_books),
    )


# Students Directory & Registration Page
@app.route('/students')
def students_page():
    students = Member.query.order_by(Member.roll_number.asc()).all()
    return render_template('students.html', students=students)


# Route to add / register a student separately
@app.route('/students/add', methods=['POST'])
def add_student():
    name = request.form.get('name', '').strip()
    roll_number = request.form.get('roll_number', '').strip().upper()
    email = request.form.get('email', '').strip()
    phone_raw = request.form.get('phone', '').strip()
    phone = validate_and_clean_phone(phone_raw)

    if not name or not roll_number or not email or not phone_raw:
        flash('All fields (Name, Roll Number, Email, and Phone Number) are required.', 'warning')
        return redirect(url_for('students_page'))

    if not phone:
        flash('Invalid Phone Number: Phone number is mandatory and must be strictly 10 digits (e.g. 9876543210).', 'danger')
        return redirect(url_for('students_page'))

    # Check for duplicate roll number
    if Member.query.filter_by(roll_number=roll_number).first():
        flash(f'A student with Roll Number "{roll_number}" is already registered.', 'warning')
        return redirect(url_for('students_page'))

    # Check for duplicate email
    if Member.query.filter_by(email=email).first():
        flash(f'A student with email "{email}" is already registered.', 'warning')
        return redirect(url_for('students_page'))

    new_student = Member(
        name=name,
        roll_number=roll_number,
        email=email,
        phone=phone,
    )
    db.session.add(new_student)
    db.session.commit()
    flash(f'Successfully registered student: {name} (Roll No: {roll_number}, Phone: {phone})', 'success')
    return redirect(url_for('students_page'))


# Route to add new books to inventory
@app.route('/admin/add-book', methods=['POST'])
@incharge_required
def add_book():
    title = request.form['title'].strip()
    author = request.form['author'].strip()
    isbn = request.form['isbn'].strip()
    category = request.form.get('category', 'Software Engineering').strip()
    copies = int(request.form.get('copies', 1))

    existing = Book.query.filter_by(isbn=isbn).first()
    if existing:
        flash(f'A book with ISBN {isbn} already exists.', 'warning')
        return redirect(url_for('catalog'))

    new_book = Book(
        title=title,
        author=author,
        isbn=isbn,
        category=category,
        total_copies=copies,
        available_copies=copies,
    )
    db.session.add(new_book)
    db.session.commit()
    flash(f'Added "{title}" to the library inventory.', 'success')
    return redirect(url_for('catalog'))


# Route to borrow a book: verifies roll number, email id, and phone number
@app.route('/borrow', methods=['POST'])
def borrow_book():
    book_id = int(request.form['book_id'])
    roll_number = request.form.get('roll_number', '').strip().upper()
    email = request.form.get('email', '').strip()
    phone_raw = request.form.get('phone', '').strip()
    phone = validate_and_clean_phone(phone_raw)

    book = Book.query.get_or_404(book_id)

    if not roll_number or not email or not phone_raw:
        flash('To borrow a book, please enter your Roll Number, Email ID, and Phone Number.', 'warning')
        return redirect(url_for('catalog'))

    if not phone:
        flash('Invalid Phone Number: Phone number is mandatory and must be strictly 10 digits (e.g. 9876543210).', 'danger')
        return redirect(url_for('catalog'))

    # Find registered student by roll number
    student = Member.query.filter_by(roll_number=roll_number).first()
    if not student:
        flash(f'No student found with Roll Number "{roll_number}". Please register your details first.', 'warning')
        return redirect(url_for('students_page'))

    # Verify that provided email and phone number match the registered student's record
    student_phone_clean = validate_and_clean_phone(student.phone)
    if student.email.lower() != email.lower() or student_phone_clean != phone:
        flash(
            f'Verification failed: Email or Phone Number does not match the registered records for Roll Number "{roll_number}".',
            'warning',
        )
        return redirect(url_for('catalog'))

    if book.available_copies <= 0:
        flash('No copies available right now. You can place a reservation instead.', 'warning')
        return redirect(url_for('catalog'))

    # Parse student-selected return date
    return_date_str = request.form.get('return_date', '').strip()
    due_date = None
    if return_date_str:
        try:
            parsed_date = datetime.strptime(return_date_str, '%Y-%m-%d')
            # Set to end of chosen day
            due_date = parsed_date.replace(hour=23, minute=59, second=59)
            if due_date.date() < datetime.utcnow().date():
                flash('Return date cannot be in the past. Please select today or a future date.', 'warning')
                return redirect(url_for('catalog'))
        except ValueError:
            due_date = None

    if not due_date:
        due_date = datetime.utcnow() + timedelta(days=14)

    book.available_copies -= 1
    new_loan = Loan(book_id=book.id, member_id=student.id, due_date=due_date)
    db.session.add(new_loan)
    db.session.commit()

    flash(
        f'Successfully checked out "{book.title}" to {student.name} ({student.roll_number})! Scheduled return date: {due_date.strftime("%b %d, %Y")}.',
        'success',
    )
    return redirect(url_for('dashboard'))


# Route to reserve a book: verifies roll number, email id, and phone number
@app.route('/reserve', methods=['POST'])
def reserve_book():
    book_id = int(request.form['book_id'])
    roll_number = request.form.get('roll_number', '').strip().upper()
    email = request.form.get('email', '').strip()
    phone_raw = request.form.get('phone', '').strip()
    phone = validate_and_clean_phone(phone_raw)

    book = Book.query.get_or_404(book_id)

    if not roll_number or not email or not phone_raw:
        flash('To place a reservation, please enter your Roll Number, Email ID, and Phone Number.', 'warning')
        return redirect(url_for('catalog'))

    if not phone:
        flash('Invalid Phone Number: Phone number is mandatory and must be strictly 10 digits (e.g. 9876543210).', 'danger')
        return redirect(url_for('catalog'))

    student = Member.query.filter_by(roll_number=roll_number).first()
    if not student:
        flash(f'No student found with Roll Number "{roll_number}". Please register your details first.', 'warning')
        return redirect(url_for('students_page'))

    student_phone_clean = validate_and_clean_phone(student.phone)
    if student.email.lower() != email.lower() or student_phone_clean != phone:
        flash(
            f'Verification failed: Email or Phone Number does not match the registered records for Roll Number "{roll_number}".',
            'warning',
        )
        return redirect(url_for('catalog'))

    existing_res = Reservation.query.filter_by(
        book_id=book_id, member_id=student.id, status='PENDING'
    ).first()

    if existing_res:
        flash(f'{student.name} already has an active waitlist hold on this book.', 'warning')
        return redirect(url_for('catalog'))

    reservation = Reservation(book_id=book_id, member_id=student.id)
    db.session.add(reservation)
    db.session.commit()

    flash(f'Reservation placed for "{book.title}" under {student.name} ({student.roll_number})! You are on the waitlist.', 'success')
    return redirect(url_for('dashboard'))


# In-Charge route to assess or update fine on a loan (in Rupees)
@app.route('/admin/loan/<int:loan_id>/fine', methods=['POST'])
@incharge_required
def assess_fine(loan_id):
    loan = Loan.query.get_or_404(loan_id)
    try:
        fine_amount = float(request.form.get('fine_amount', 0.0))
    except (ValueError, TypeError):
        fine_amount = 0.0

    fine_status = request.form.get('fine_status', 'UNPAID')
    fine_reason = request.form.get('fine_reason', '').strip()

    loan.fine_amount = max(0.0, fine_amount)
    loan.fine_status = fine_status
    loan.fine_reason = fine_reason
    loan.processed_by = session.get('incharge_name', 'Library In-Charge')
    db.session.commit()

    incharge_name = session.get('incharge_name', 'In-Charge')
    if fine_status == 'PAID':
        flash(
            f'Fine of ₹{loan.fine_amount:.2f} marked as PAID by In-Charge {incharge_name}. Overdue notification removed for {loan.member.name} ({loan.member.roll_number}).',
            'success',
        )
    else:
        flash(
            f'Fine assessment of ₹{loan.fine_amount:.2f} ({fine_status}) recorded by In-Charge {incharge_name} for {loan.member.name} ({loan.member.roll_number}) on "{loan.book.title}".',
            'success',
        )
    return redirect(url_for('dashboard'))


# In-Charge route to mark an outstanding fine as PAID (removes overdue notification)
@app.route('/admin/loan/<int:loan_id>/pay-fine', methods=['POST'])
@incharge_required
def pay_fine(loan_id):
    loan = Loan.query.get_or_404(loan_id)
    if loan.fine_amount == 0.0 and loan.overdue_days > 0:
        loan.fine_amount = loan.suggested_fine
        loan.fine_reason = f'{loan.overdue_days} days overdue (₹10/day)'
    loan.fine_status = 'PAID'
    loan.processed_by = session.get('incharge_name', 'Library In-Charge')
    db.session.commit()

    incharge_name = session.get('incharge_name', 'In-Charge')
    flash(
        f'Fine of ₹{loan.fine_amount:.2f} collected and marked PAID by In-Charge {incharge_name}. Overdue notification removed for {loan.member.name} ({loan.member.roll_number}).',
        'success',
    )
    return redirect(url_for('dashboard'))


# In-Charge route to waive an outstanding fine
@app.route('/admin/loan/<int:loan_id>/waive-fine', methods=['POST'])
@incharge_required
def waive_fine(loan_id):
    loan = Loan.query.get_or_404(loan_id)
    loan.fine_status = 'WAIVED'
    loan.processed_by = session.get('incharge_name', 'Library In-Charge')
    db.session.commit()

    incharge_name = session.get('incharge_name', 'In-Charge')
    flash(
        f'Fine waived by In-Charge {incharge_name} for {loan.member.name} ({loan.member.roll_number}). Overdue notification cleared.',
        'info',
    )
    return redirect(url_for('dashboard'))


# Return book route with fine calculation in Rupees — ONLY IN-CHARGE CAN MARK RETURNED
@app.route('/return/<int:loan_id>', methods=['POST'])
@incharge_required
def return_book(loan_id):
    loan = Loan.query.get_or_404(loan_id)
    now = datetime.utcnow()
    loan.returned_date = now
    loan.status = 'RETURNED'
    loan.processed_by = session.get('incharge_name', 'Library In-Charge')

    fine_msg = ''
    # If book was overdue
    if now > loan.due_date:
        overdue_days = (now - loan.due_date).days or 1
        # If fine was not explicitly assessed, compute standard overdue fine in Rupees (₹10/day)
        if loan.fine_amount == 0.0:
            loan.fine_amount = overdue_days * 10.0
            loan.fine_status = 'UNPAID'
            loan.fine_reason = f'{overdue_days} day(s) overdue late fine (₹10/day)'
        fine_msg = f' Late fine charged: ₹{loan.fine_amount:.2f} ({loan.fine_status}). Overdue notification will remain until marked PAID by in-charge.'
    elif loan.fine_amount > 0:
        fine_msg = f' Fine record: ₹{loan.fine_amount:.2f} ({loan.fine_status}).'

    book = loan.book
    pending_res = (
        Reservation.query.filter_by(book_id=book.id, status='PENDING')
        .order_by(Reservation.reserved_date.asc())
        .first()
    )

    incharge_name = session.get('incharge_name', 'In-Charge')
    if pending_res:
        # Hold copy for the waitlisted student and prompt in-charge to notify them
        pending_res.status = 'READY_FOR_PICKUP'
        pending_res.notified_date = now
        flash(
            f'Book "{book.title}" returned and verified by In-Charge {incharge_name}.{fine_msg} Copy is now HELD for waitlist student {pending_res.member.name} ({pending_res.member.roll_number}). Please notify them for pickup!',
            'info',
        )
    else:
        book.available_copies += 1
        flash(f'Book "{book.title}" marked RETURNED by In-Charge {incharge_name}.{fine_msg} Restored to active inventory.', 'success')

    db.session.commit()
    return redirect(url_for('dashboard'))


# In-Charge route to notify a waitlist student that their held book is ready
@app.route('/admin/reservation/<int:res_id>/notify', methods=['POST'])
@incharge_required
def notify_waitlist_student(res_id):
    res = Reservation.query.get_or_404(res_id)
    res.notified_date = datetime.utcnow()
    if res.status == 'PENDING':
        res.status = 'READY_FOR_PICKUP'
    db.session.commit()

    incharge_name = session.get('incharge_name', 'In-Charge')
    flash(
        f'Pickup contact logged by In-Charge {incharge_name} for {res.member.name} ({res.member.roll_number})! Book "{res.book.title}" is held. Student contact: 📞 {res.member.phone} | ✉️ {res.member.email}.',
        'success',
    )
    return redirect(url_for('dashboard'))


# In-Charge route to issue/checkout the held book to the waitlist student
@app.route('/admin/reservation/<int:res_id>/fulfill', methods=['POST'])
@incharge_required
def fulfill_waitlist_reservation(res_id):
    res = Reservation.query.get_or_404(res_id)
    due_date = datetime.utcnow() + timedelta(days=14)

    # Create new loan for waitlist student
    incharge_name = session.get('incharge_name', 'Library In-Charge')
    new_loan = Loan(book_id=res.book_id, member_id=res.member_id, due_date=due_date, processed_by=incharge_name)
    res.status = 'FULFILLED'
    db.session.add(new_loan)
    db.session.commit()

    flash(
        f'Waitlist fulfilled by In-Charge {incharge_name}! Successfully issued "{res.book.title}" to {res.member.name} ({res.member.roll_number}). Scheduled return: {due_date.strftime("%b %d, %Y")}.',
        'success',
    )
    return redirect(url_for('dashboard'))


# In-Charge route to cancel a waitlist reservation
@app.route('/admin/reservation/<int:res_id>/cancel', methods=['POST'])
@incharge_required
def cancel_waitlist_reservation(res_id):
    res = Reservation.query.get_or_404(res_id)
    book = res.book
    prev_status = res.status
    res.status = 'CANCELLED'

    incharge_name = session.get('incharge_name', 'In-Charge')
    # If the book was held for this student, assign to next pending student or return to stock
    if prev_status == 'READY_FOR_PICKUP':
        next_res = (
            Reservation.query.filter_by(book_id=book.id, status='PENDING')
            .order_by(Reservation.reserved_date.asc())
            .first()
        )
        if next_res:
            next_res.status = 'READY_FOR_PICKUP'
            next_res.notified_date = datetime.utcnow()
            flash(f'Waitlist cancelled by In-Charge {incharge_name} for {res.member.name}. Book is now held for next student: {next_res.member.name}.', 'info')
        else:
            book.available_copies += 1
            flash(f'Waitlist cancelled by In-Charge {incharge_name} for {res.member.name}. Copy restored to available stock.', 'info')
    else:
        flash(f'Waitlist reservation cancelled by In-Charge {incharge_name} for {res.member.name}.', 'info')

    db.session.commit()
    return redirect(url_for('dashboard'))


# ── In-Charge Route: Renew / Extend Loan by 14 Days ───────────────────────────
@app.route('/admin/loan/<int:loan_id>/renew', methods=['POST'])
@incharge_required
def renew_loan(loan_id):
    loan = Loan.query.get_or_404(loan_id)
    if loan.status != 'ACTIVE':
        flash('Only active loans can be renewed.', 'warning')
        return redirect(url_for('dashboard'))

    # Check if any waitlist reservation exists for this book
    waitlist = Reservation.query.filter_by(book_id=loan.book_id, status='PENDING').first()
    if waitlist:
        flash(
            f'Renewal Blocked: Student {waitlist.member.name} ({waitlist.member.roll_number}) is waiting in queue for "{loan.book.title}". Please have the student return it on schedule.',
            'danger',
        )
        return redirect(url_for('dashboard'))

    base_date = max(loan.due_date, datetime.utcnow())
    loan.due_date = base_date + timedelta(days=14)
    loan.processed_by = session.get('incharge_name', 'Library In-Charge')
    db.session.commit()

    flash(
        f'Loan extended by 14 days for {loan.member.name}! New return deadline: {loan.due_date.strftime("%b %d, %Y")}.',
        'success',
    )
    return redirect(url_for('dashboard'))


# ── In-Charge Route: Export Circulation Report to CSV ─────────────────────────
@app.route('/admin/export/loans')
@incharge_required
def export_loans():
    loans = Loan.query.order_by(Loan.borrowed_date.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Loan ID', 'Student Roll', 'Student Name', 'Phone', 'Email',
        'Book Title', 'ISBN', 'Category', 'Borrowed Date', 'Due Date',
        'Returned Date', 'Status', 'Overdue Days', 'Fine Amount (INR)',
        'Fine Status', 'Fine Reason', 'Handled By In-Charge'
    ])
    for l in loans:
        writer.writerow([
            l.id,
            l.member.roll_number,
            l.member.name,
            l.member.phone,
            l.member.email,
            l.book.title,
            l.book.isbn,
            l.book.category,
            l.borrowed_date.strftime('%Y-%m-%d %H:%M') if l.borrowed_date else '',
            l.due_date.strftime('%Y-%m-%d') if l.due_date else '',
            l.returned_date.strftime('%Y-%m-%d %H:%M') if l.returned_date else '',
            l.status,
            l.overdue_days,
            f'₹{l.fine_amount:.2f}',
            l.fine_status,
            l.fine_reason or '',
            l.processed_by or 'N/A'
        ])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=LibFlow_Circulation_Report.csv'}
    )


# ── In-Charge Route: Export Catalog Inventory to CSV ──────────────────────────
@app.route('/admin/export/books')
@incharge_required
def export_books():
    books = Book.query.order_by(Book.category.asc(), Book.title.asc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Book ID', 'Title', 'Author', 'Category', 'ISBN',
        'Total Copies', 'Available Copies', 'Borrowed Count', 'Average Rating', 'Reviews Count'
    ])
    for b in books:
        writer.writerow([
            b.id,
            b.title,
            b.author,
            b.category,
            b.isbn,
            b.total_copies,
            b.available_copies,
            len(b.loans),
            f'{b.average_rating} / 5',
            b.review_count
        ])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=LibFlow_Catalog_Inventory.csv'}
    )


# ── Student Book Reviews API & Submission ─────────────────────────────────────
@app.route('/books/<int:book_id>/review', methods=['POST'])
def submit_review(book_id):
    book = Book.query.get_or_404(book_id)
    roll_number = request.form.get('roll_number', '').strip().upper()
    student_name = request.form.get('student_name', '').strip()
    try:
        rating = int(request.form.get('rating', 5))
    except (ValueError, TypeError):
        rating = 5
    comment = request.form.get('comment', '').strip()

    if not roll_number or not comment:
        flash('Roll number and review comments are required.', 'warning')
        return redirect(url_for('catalog'))

    student = Member.query.filter_by(roll_number=roll_number).first()
    if student:
        student_name = student.name
    elif not student_name:
        student_name = f'Student ({roll_number})'

    review = Review(
        book_id=book.id,
        student_name=student_name,
        roll_number=roll_number,
        rating=max(1, min(5, rating)),
        comment=comment
    )
    db.session.add(review)
    db.session.commit()
    flash(f'Thank you, {student_name}! Your review for "{book.title}" has been published ⭐.', 'success')
    return redirect(url_for('catalog'))


@app.route('/api/books/<int:book_id>/reviews')
def get_book_reviews(book_id):
    book = Book.query.get_or_404(book_id)
    reviews_data = [
        {
            'id': r.id,
            'student_name': r.student_name,
            'roll_number': r.roll_number,
            'rating': r.rating,
            'comment': r.comment,
            'date': r.created_at.strftime('%b %d, %Y')
        }
        for r in book.reviews
    ]
    return jsonify({
        'book_title': book.title,
        'book_author': book.author,
        'average_rating': book.average_rating,
        'review_count': book.review_count,
        'reviews': reviews_data
    })


@app.route('/dashboard')
@incharge_required
def dashboard():
    search_query = request.args.get('q', '').strip()

    # Active loans query (with search support)
    query = Loan.query.filter_by(status='ACTIVE')
    if search_query:
        query = query.join(Member).join(Book).filter(
            (Member.name.ilike(f'%{search_query}%'))
            | (Member.roll_number.ilike(f'%{search_query}%'))
            | (Book.title.ilike(f'%{search_query}%'))
            | (Book.isbn.ilike(f'%{search_query}%'))
        )
    active_loans = query.order_by(Loan.due_date.asc()).all()

    # Overdue notifications: Any overdue loan (active or returned) where fine is NOT marked PAID by in-charge
    all_loans = Loan.query.order_by(Loan.due_date.asc()).all()
    overdue_notifications = [
        loan for loan in all_loans
        if (loan.is_overdue or (loan.status == 'RETURNED' and loan.overdue_days > 0 and loan.fine_status == 'UNPAID'))
        and loan.fine_status not in ('PAID', 'WAIVED')
    ]

    # Active reservations (PENDING or READY_FOR_PICKUP)
    reservations = (
        Reservation.query.filter(Reservation.status.in_(['PENDING', 'READY_FOR_PICKUP']))
        .order_by(Reservation.reserved_date.asc())
        .all()
    )

    # Distinct students carrying active loans
    students_with_loans = (
        Member.query.join(Loan)
        .filter(Loan.status == 'ACTIVE')
        .distinct()
        .order_by(Member.roll_number.asc())
        .all()
    )

    # Total unpaid fines among active/unsettled loans in Rupees
    total_fines_unpaid = sum(
        l.fine_amount if l.fine_amount > 0 else l.suggested_fine
        for l in overdue_notifications
    )

    # === Honor Board: Students with clean records (no unpaid fines, at least 1 past loan) ===
    all_members = Member.query.all()
    honor_students = []
    for m in all_members:
        past_loans = [l for l in m.loans if l.status == 'RETURNED']
        unpaid_fines = [l for l in m.loans if l.fine_status == 'UNPAID']
        if past_loans and not unpaid_fines:
            honor_students.append({
                'member': m,
                'books_returned': len(past_loans),
                'active_now': len(m.active_loans),
            })
    # Sort by most books returned
    honor_students.sort(key=lambda x: x['books_returned'], reverse=True)

    # === Recent activity (last 5 loans/returns) ===
    recent_activity = Loan.query.order_by(Loan.id.desc()).limit(8).all()

    # === Today's stats ===
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    loans_today = Loan.query.filter(Loan.borrowed_date >= today_start).count()
    returns_today = Loan.query.filter(
        Loan.returned_date >= today_start,
        Loan.status == 'RETURNED'
    ).count()

    # === In-Charges List (Maximum 2) ===
    incharges = Incharge.query.order_by(Incharge.id.asc()).all()

    return render_template(
        'dashboard.html',
        active_loans=active_loans,
        overdue_notifications=overdue_notifications,
        reservations=reservations,
        students_with_loans=students_with_loans,
        total_fines_unpaid=total_fines_unpaid,
        search_query=search_query,
        honor_students=honor_students,
        recent_activity=recent_activity,
        loans_today=loans_today,
        returns_today=returns_today,
        incharges=incharges,
        now=datetime.utcnow(),
    )


def setup_initial_data():
    with app.app_context():
        db.create_all()

        # Seed the 2 In-Charge accounts (Maximum 2 In-Charges strictly permitted)
        if Incharge.query.count() == 0:
            inc1 = Incharge(
                username='incharge1',
                name='Suresh Sharma (In-Charge 1)',
                role='Chief Library In-Charge',
                email='incharge1@university.edu',
                phone='9876543201',
            )
            inc1.set_password('admin123')

            inc2 = Incharge(
                username='incharge2',
                name='Priya Patel (In-Charge 2)',
                role='Assistant Library In-Charge',
                email='incharge2@university.edu',
                phone='9876543202',
            )
            inc2.set_password('admin123')

            db.session.add_all([inc1, inc2])
            db.session.commit()

        if not Book.query.first():
            db.session.add_all([
                Book(title='Clean Code', author='Robert C. Martin', isbn='9780132350884', category='Software Engineering', total_copies=2, available_copies=2),
                Book(title='Design Patterns (GoF)', author='Erich Gamma et al.', isbn='9780201633610', category='Software Engineering', total_copies=1, available_copies=1),
                Book(title='Refactoring', author='Martin Fowler', isbn='9780201485677', category='Software Engineering', total_copies=2, available_copies=2),
                Book(title='The Pragmatic Programmer', author='Andrew Hunt & David Thomas', isbn='9780135957059', category='Software Engineering', total_copies=3, available_copies=3),
                Book(title='The Mythical Man-Month', author='Frederick P. Brooks Jr.', isbn='9780201835953', category='Software Engineering', total_copies=3, available_copies=3),
                Book(title='Head First Design Patterns', author='Eric Freeman & Elisabeth Robson', isbn='9781492078005', category='Software Engineering', total_copies=4, available_copies=4),
                Book(title='Designing Data-Intensive Applications', author='Martin Kleppmann', isbn='9781449373320', category='Systems & Cloud', total_copies=4, available_copies=4),
                Book(title='Operating System Concepts', author='Abraham Silberschatz et al.', isbn='9781119800361', category='Systems & Cloud', total_copies=3, available_copies=3),
                Book(title='Database System Concepts', author='Abraham Silberschatz et al.', isbn='9780078022159', category='Systems & Cloud', total_copies=2, available_copies=2),
                Book(title='Site Reliability Engineering (Google SRE)', author='Betsy Beyer et al.', isbn='9781491929124', category='Systems & Cloud', total_copies=4, available_copies=4),
                Book(title='Artificial Intelligence: A Modern Approach', author='Stuart Russell & Peter Norvig', isbn='9780134610993', category='Artificial Intelligence', total_copies=2, available_copies=2),
                Book(title='Life 3.0: Being Human in the Age of AI', author='Max Tegmark', isbn='9781101946596', category='Artificial Intelligence', total_copies=3, available_copies=3),
                Book(title='Superintelligence: Paths, Dangers, Strategies', author='Nick Bostrom', isbn='9780199678112', category='Artificial Intelligence', total_copies=2, available_copies=2),
                Book(title='Computer Networking: A Top-Down Approach', author='James Kurose & Keith Ross', isbn='9780136681557', category='Cybersecurity & Networks', total_copies=3, available_copies=3),
                Book(title='The Code Book: The Science of Secrecy', author='Simon Singh', isbn='9780385495325', category='Cybersecurity & Networks', total_copies=3, available_copies=3),
                Book(title='Hacking: The Art of Exploitation', author='Jon Erickson', isbn='9781593271442', category='Cybersecurity & Networks', total_copies=2, available_copies=2),
                Book(title='Introduction to Algorithms (CLRS)', author='Thomas H. Cormen et al.', isbn='9780262046305', category='Algorithms & Theory', total_copies=2, available_copies=2),
                Book(title='Structure and Interpretation of Computer Programs', author='Harold Abelson & Gerald Jay Sussman', isbn='9780262510875', category='Algorithms & Theory', total_copies=2, available_copies=2),
                Book(title='Gödel, Escher, Bach: An Eternal Golden Braid', author='Douglas Hofstadter', isbn='9780465026562', category='Science & Futurism', total_copies=2, available_copies=2),
                Book(title='Cosmos: A Personal Voyage', author='Carl Sagan', isbn='9780345539434', category='Science & Futurism', total_copies=3, available_copies=3),
                Book(title='Zero to One: Notes on Startups', author='Peter Thiel & Blake Masters', isbn='9780804139298', category='Innovation & Strategy', total_copies=4, available_copies=4),
                Book(title="You Don't Know JS Yet: Get Started", author='Kyle Simpson', isbn='9781098175542', category='Web Development', total_copies=3, available_copies=3),
                Member(name='Alice Johnson', roll_number='24CS101', email='alice@example.com', phone='9876543210'),
                Member(name='Bob Smith', roll_number='24CS102', email='bob@example.com', phone='9876543211'),
                Member(name='Charlie Brown', roll_number='24CS103', email='charlie@example.com', phone='9876543212'),
                Member(name='Diana Prince', roll_number='24CS104', email='diana@example.com', phone='9876543213'),
                Member(name='Evan Wright', roll_number='24CS105', email='evan@example.com', phone='9876543214'),
                Member(name='Fiona Gallagher', roll_number='24CS106', email='fiona@example.com', phone='9876543215'),
                Member(name='George Clark', roll_number='24CS107', email='george@example.com', phone='9876543216'),
            ])
            db.session.commit()


if __name__ == '__main__':
    setup_initial_data()
    app.run(debug=True)
