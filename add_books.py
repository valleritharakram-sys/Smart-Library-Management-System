"""Script to add new books across new categories to LibFlow."""
from app import app
from models import db, Book

NEW_BOOKS = [
    # ── Python & Programming Languages ─────────────────────────────────────────
    dict(title='Python Crash Course',              author='Eric Matthes',                    isbn='9781718502703', category='Python & Programming', total_copies=4, available_copies=4),
    dict(title='Fluent Python',                    author='Luciano Ramalho',                 isbn='9781492056355', category='Python & Programming', total_copies=3, available_copies=3),
    dict(title='Automate the Boring Stuff with Python', author='Al Sweigart',                isbn='9781593279929', category='Python & Programming', total_copies=4, available_copies=4),
    dict(title='Learning Python',                  author='Mark Lutz',                       isbn='9781449355739', category='Python & Programming', total_copies=2, available_copies=2),
    dict(title='Python Cookbook',                  author='David Beazley & Brian K. Jones',  isbn='9781449340377', category='Python & Programming', total_copies=3, available_copies=3),
    dict(title='Effective Python',                 author='Brett Slatkin',                   isbn='9780134853987', category='Python & Programming', total_copies=2, available_copies=2),
    dict(title='Python for Everybody',             author='Charles Severance',               isbn='9781530051120', category='Python & Programming', total_copies=5, available_copies=5),

    # ── Blockchain & Web3 ───────────────────────────────────────────────────────
    dict(title='Mastering Bitcoin',                author='Andreas M. Antonopoulos',         isbn='9781491954386', category='Blockchain & Web3',   total_copies=3, available_copies=3),
    dict(title='Mastering Ethereum',               author='Andreas Antonopoulos & Gavin Wood',isbn='9781491971949',category='Blockchain & Web3',   total_copies=3, available_copies=3),
    dict(title='The Bitcoin Standard',             author='Saifedean Ammous',                isbn='9781119473862', category='Blockchain & Web3',   total_copies=2, available_copies=2),
    dict(title='Blockchain Revolution',            author='Don Tapscott & Alex Tapscott',   isbn='9781101980132', category='Blockchain & Web3',   total_copies=3, available_copies=3),
    dict(title='Token Economy',                    author='Shermin Voshmgir',                isbn='9783982103907', category='Blockchain & Web3',   total_copies=2, available_copies=2),
    dict(title='Cryptoassets',                     author='Chris Burniske & Jack Tatar',     isbn='9781260026671', category='Blockchain & Web3',   total_copies=2, available_copies=2),

    # ── Data Science & Analytics ────────────────────────────────────────────────
    dict(title='Python for Data Analysis',         author='Wes McKinney',                    isbn='9781491957660', category='Data Science & Analytics', total_copies=3, available_copies=3),
    dict(title='Hands-On Machine Learning (Géron)',author='Aurélien Géron',                  isbn='9781492032649', category='Data Science & Analytics', total_copies=3, available_copies=3),
    dict(title='Data Science from Scratch',        author='Joel Grus',                       isbn='9781492041139', category='Data Science & Analytics', total_copies=2, available_copies=2),
    dict(title='The Elements of Statistical Learning', author='Hastie, Tibshirani & Friedman',isbn='9780387848570',category='Data Science & Analytics', total_copies=2, available_copies=2),
    dict(title='Storytelling with Data',           author='Cole Nussbaumer Knaflic',         isbn='9781119002253', category='Data Science & Analytics', total_copies=3, available_copies=3),
    dict(title='Practical Statistics for Data Scientists', author='Peter Bruce & Andrew Bruce', isbn='9781492072942', category='Data Science & Analytics', total_copies=2, available_copies=2),

    # ── DevOps & Automation ─────────────────────────────────────────────────────
    dict(title='The Phoenix Project',              author='Gene Kim, Kevin Behr & George Spafford', isbn='9781942788294', category='DevOps & Automation', total_copies=3, available_copies=3),
    dict(title='Kubernetes in Action',             author='Marko Luksa',                     isbn='9781617293726', category='DevOps & Automation', total_copies=2, available_copies=2),
    dict(title='Docker Deep Dive',                 author='Nigel Poulton',                   isbn='9781521822807', category='DevOps & Automation', total_copies=3, available_copies=3),
    dict(title='Continuous Delivery',              author='Jez Humble & David Farley',       isbn='9780321601919', category='DevOps & Automation', total_copies=2, available_copies=2),
    dict(title='The DevOps Handbook',              author='Gene Kim et al.',                 isbn='9781942788003', category='DevOps & Automation', total_copies=3, available_copies=3),
    dict(title='Terraform: Up & Running',          author='Yevgeniy Brikman',                isbn='9781492046905', category='DevOps & Automation', total_copies=2, available_copies=2),

    # ── Mathematics for CS ──────────────────────────────────────────────────────
    dict(title='Discrete Mathematics and Its Applications', author='Kenneth H. Rosen',       isbn='9781259676512', category='Mathematics for CS',  total_copies=3, available_copies=3),
    dict(title='Linear Algebra Done Right',        author='Sheldon Axler',                   isbn='9783319307657', category='Mathematics for CS',  total_copies=2, available_copies=2),
    dict(title='Concrete Mathematics',             author='Graham, Knuth & Patashnik',       isbn='9780201558029', category='Mathematics for CS',  total_copies=2, available_copies=2),
    dict(title='Mathematics for Machine Learning', author='Deisenroth, Faisal & Ong',       isbn='9781108455145', category='Mathematics for CS',  total_copies=3, available_copies=3),
    dict(title='Probability Theory: The Logic of Science', author='E.T. Jaynes',            isbn='9780521592710', category='Mathematics for CS',  total_copies=2, available_copies=2),

    # ── Mobile & App Development ────────────────────────────────────────────────
    dict(title='Android Programming: Big Nerd Ranch Guide', author='Bill Phillips et al.',   isbn='9780135245132', category='Mobile & App Dev',   total_copies=2, available_copies=2),
    dict(title='iOS Programming: Big Nerd Ranch Guide', author='Christian Keur & Aaron Hillegass', isbn='9780135264027', category='Mobile & App Dev', total_copies=2, available_copies=2),
    dict(title='Flutter in Action',                author='Eric Windmill',                   isbn='9781617296147', category='Mobile & App Dev',   total_copies=3, available_copies=3),
    dict(title='React Native in Action',           author='Nader Dabit',                     isbn='9781617294051', category='Mobile & App Dev',   total_copies=2, available_copies=2),

    # ── Clean / Extra Software Engineering ──────────────────────────────────────
    dict(title='A Philosophy of Software Design',  author='John Ousterhout',                 isbn='9781732102200', category='Software Engineering', total_copies=3, available_copies=3),
    dict(title='Working Effectively with Legacy Code', author='Michael C. Feathers',         isbn='9780131177055', category='Software Engineering', total_copies=2, available_copies=2),
    dict(title='Domain-Driven Design',             author='Eric Evans',                      isbn='9780321125217', category='Software Engineering', total_copies=2, available_copies=2),

    # ── Extra Cybersecurity ──────────────────────────────────────────────────────
    dict(title='The Web Application Hacker\'s Handbook', author='Stuttard & Pinto',         isbn='9781118026472', category='Cybersecurity & Networks', total_copies=2, available_copies=2),
    dict(title='Penetration Testing',              author='Georgia Weidman',                 isbn='9781593275648', category='Cybersecurity & Networks', total_copies=2, available_copies=2),

    # ── Extra AI ─────────────────────────────────────────────────────────────────
    dict(title='Deep Learning',                    author='Goodfellow, Bengio & Courville',  isbn='9780262035613', category='Artificial Intelligence', total_copies=2, available_copies=2),
    dict(title='Reinforcement Learning',           author='Sutton & Barto',                  isbn='9780262039246', category='Artificial Intelligence', total_copies=2, available_copies=2),
    dict(title='The Hundred-Page Machine Learning Book', author='Andriy Burkov',             isbn='9781999579517', category='Artificial Intelligence', total_copies=3, available_copies=3),
]

def add_books():
    with app.app_context():
        added = 0
        skipped = 0
        for data in NEW_BOOKS:
            exists = Book.query.filter_by(isbn=data['isbn']).first()
            if exists:
                skipped += 1
                continue
            db.session.add(Book(**data))
            added += 1
        db.session.commit()
        print(f"✅ Added {added} new books | ⏭️  Skipped {skipped} duplicates")

        # Print summary by category
        from sqlalchemy import func
        rows = db.session.query(Book.category, func.count(Book.id)).group_by(Book.category).order_by(Book.category).all()
        print("\n📚 Catalog summary by category:")
        total = 0
        for cat, count in rows:
            print(f"  {cat:<35} {count} book(s)")
            total += count
        print(f"\n  TOTAL: {total} books")

if __name__ == '__main__':
    add_books()
