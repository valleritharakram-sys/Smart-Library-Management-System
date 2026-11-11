"""
LibFlow Smart Search Engine
Multi-layer AI-powered search using:
  1. Synonym/abbreviation expansion
  2. Fuzzy matching (difflib)
  3. NLP keyword intent parsing
  4. Relevance scoring & ranking
  5. Query suggestions / "Did you mean?"
  6. Gemini LLM (optional — only if GEMINI_API_KEY env var is set)
"""
import os
import re
import difflib
from typing import Optional


# ── 1. Abbreviation / Synonym Map ──────────────────────────────────────────────
SYNONYMS = {
    # Abbreviations
    "ai": ["artificial intelligence", "machine learning", "deep learning"],
    "ml": ["machine learning", "artificial intelligence"],
    "dl": ["deep learning", "neural network"],
    "os": ["operating system", "systems"],
    "db": ["database", "data"],
    "cs": ["computer science", "algorithms"],
    "dsa": ["algorithms", "data structures"],
    "se": ["software engineering"],
    "cloud": ["cloud computing", "systems", "site reliability"],
    "web": ["web development", "javascript"],
    "js": ["javascript", "web development"],
    "net": ["networking", "computer networking"],
    "sec": ["security", "cybersecurity", "hacking"],
    "hack": ["hacking", "cybersecurity", "exploitation"],
    "crypto": ["cryptography", "code book", "secrecy"],
    "algo": ["algorithms", "introduction to algorithms"],
    "algos": ["algorithms", "introduction to algorithms"],
    "ds": ["data structures", "algorithms"],
    "sre": ["site reliability engineering", "google sre"],
    "ddia": ["designing data-intensive"],
    "clrs": ["introduction to algorithms"],
    "sicp": ["structure and interpretation"],
    "gof": ["design patterns"],
    "geb": ["godel escher bach", "hofstadter"],
    "startup": ["zero to one", "innovation", "strategy"],
    "refactor": ["refactoring", "martin fowler"],
    "clean": ["clean code", "robert martin"],
    "pragmatic": ["pragmatic programmer"],
    # Topic synonyms
    "security": ["cybersecurity", "hacking", "cryptography", "exploitation"],
    "network": ["networking", "computer networking"],
    "data": ["database", "data-intensive", "data structures"],
    "philosophy": ["godel", "escher", "bach", "hofstadter"],
    "space": ["cosmos", "carl sagan", "science"],
    "future": ["life 3.0", "superintelligence", "science", "futurism"],
    "robot": ["artificial intelligence", "superintelligence"],
    "code": ["clean code", "software engineering"],
    "pattern": ["design patterns", "head first design patterns"],
    "concurrent": ["operating system", "systems"],
    "distributed": ["designing data-intensive", "site reliability"],
    "functional": ["structure and interpretation", "sicp"],
    "oop": ["design patterns", "clean code", "head first"],
    "agile": ["pragmatic programmer", "software engineering"],
    "testing": ["clean code", "refactoring", "pragmatic"],
    # Python
    "python": ["python crash course", "fluent python", "automate", "learning python"],
    "py": ["python", "fluent python"],
    "pandas": ["python for data analysis", "data science"],
    "automation": ["automate the boring stuff", "devops"],
    "scripting": ["python", "automate the boring stuff"],
    # Blockchain
    "blockchain": ["mastering bitcoin", "mastering ethereum", "blockchain revolution"],
    "bitcoin": ["mastering bitcoin", "bitcoin standard"],
    "ethereum": ["mastering ethereum", "token economy"],
    "web3": ["mastering ethereum", "blockchain", "token economy"],
    "defi": ["mastering ethereum", "blockchain"],
    "nft": ["token economy", "mastering ethereum"],
    "satoshi": ["mastering bitcoin", "bitcoin standard"],
    "crypto": ["cryptoassets", "mastering bitcoin", "token economy"],
    # Data Science
    "numpy": ["python for data analysis", "data science"],
    "visualization": ["storytelling with data", "data science"],
    "stats": ["practical statistics", "elements of statistical learning"],
    "statistics": ["practical statistics", "elements of statistical learning"],
    "analytics": ["data science", "storytelling with data"],
    # DevOps
    "devops": ["phoenix project", "devops handbook", "continuous delivery"],
    "docker": ["docker deep dive", "kubernetes"],
    "k8s": ["kubernetes in action"],
    "kubernetes": ["kubernetes in action"],
    "terraform": ["terraform up running", "infrastructure"],
    "cicd": ["continuous delivery", "devops handbook"],
    "infrastructure": ["terraform", "kubernetes", "site reliability engineering"],
    "deployment": ["continuous delivery", "kubernetes", "docker"],
    # Mobile
    "android": ["android programming", "mobile"],
    "ios": ["ios programming", "swift"],
    "flutter": ["flutter in action"],
    "mobile": ["android programming", "ios programming", "flutter in action", "react native"],
    "app": ["android programming", "ios programming", "flutter"],
    # Math
    "math": ["discrete mathematics", "linear algebra", "concrete mathematics"],
    "maths": ["discrete mathematics", "linear algebra", "mathematics for machine learning"],
    "discrete": ["discrete mathematics and its applications"],
    "probability": ["probability theory", "practical statistics"],
    # Generic (ignored)
    "book": [],
    "good": [],
    "best": [],
    "popular": [],
    "famous": [],
    "must": [],
    "read": [],
    "want": [],
    "need": [],
    "find": [],
    "show": [],
    "get": [],
    "give": [],
}

# Common stop words for NLP parsing
STOP_WORDS = {
    "a", "an", "the", "and", "or", "for", "in", "on", "about",
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did",
    "i", "me", "my", "we", "you", "your", "he", "she", "it", "they",
    "want", "need", "find", "show", "get", "give", "can", "could",
    "would", "should", "will", "may", "might", "shall",
    "some", "any", "all", "both", "few", "more", "most",
    "book", "books", "read", "reading", "library", "topic",
    "related", "about", "something", "that", "this", "these", "those",
}


def expand_query(query: str) -> list[str]:
    """Expand abbreviations and synonyms into alternative search terms."""
    tokens = re.findall(r'\w+', query.lower())
    expanded = set()
    for tok in tokens:
        if tok in STOP_WORDS:
            continue
        expanded.add(tok)
        if tok in SYNONYMS:
            expanded.update(SYNONYMS[tok])
    return list(expanded)


def score_book(book, expanded_terms: list[str], original_query: str) -> float:
    """
    Score a book against a query. Higher = more relevant.
    Weights: exact title match > author match > category > ISBN > fuzzy
    """
    score = 0.0
    q_lower = original_query.lower()

    text_fields = {
        'title':    (book.title.lower(),    8.0),
        'author':   (book.author.lower(),   5.0),
        'category': (book.category.lower(), 4.0),
        'isbn':     (book.isbn.lower(),     3.0),
    }

    combined = f"{book.title} {book.author} {book.category}".lower()

    # Exact full query match in title → massive boost
    if q_lower in book.title.lower():
        score += 20.0
    if q_lower in book.author.lower():
        score += 10.0
    if q_lower in book.category.lower():
        score += 8.0

    # Per-term scoring
    for term in expanded_terms:
        if len(term) < 2:
            continue
        for field, (field_val, weight) in text_fields.items():
            if term in field_val:
                score += weight
            else:
                # Fuzzy match for each field
                ratio = difflib.SequenceMatcher(None, term, field_val).ratio()
                # Only count fuzzy if reasonably similar
                if ratio > 0.6:
                    score += weight * ratio * 0.5
                # Partial / substring fuzzy
                for word in re.split(r'\W+', field_val):
                    if len(word) < 3:
                        continue
                    r = difflib.SequenceMatcher(None, term, word).ratio()
                    if r > 0.75:
                        score += weight * r * 0.4

    # Availability boost (+1 if available)
    if book.available_copies > 0:
        score += 1.0

    # Popularity boost
    score += min(len(book.loans) * 0.3, 3.0)

    return score


def ai_search(books, query: str, top_n: int = 50):
    """
    Main AI search function.
    Returns (ranked_books, suggestions, intent_label, expanded_terms)
    """
    if not query or not query.strip():
        return books, [], None, []

    q = query.strip()
    expanded = expand_query(q)

    # Score all books
    scored = []
    for book in books:
        s = score_book(book, expanded, q)
        if s > 0:
            scored.append((s, book))

    scored.sort(key=lambda x: x[0], reverse=True)
    ranked = [b for _, b in scored[:top_n]]

    # "Did you mean?" suggestions — find close title matches for original query
    suggestions = []
    if not ranked or (len(ranked) < 3 and len(q) > 3):
        all_titles = [b.title for b in books]
        close = difflib.get_close_matches(q, all_titles, n=3, cutoff=0.4)
        suggestions = close

    # Detect query intent for a friendly label
    intent = detect_intent(q, expanded)

    return ranked, suggestions, intent, expanded


def detect_intent(query: str, expanded: list[str]) -> Optional[str]:
    """Classify the user's intent into a friendly label."""
    q = query.lower()
    intent_map = [
        (["available", "free", "borrow now"],                                   "📗 Showing available books"),
        (["overdue", "late", "fine"],                                            "⏰ Overdue & fine-related"),
        (["python", "py", "fluent", "automate", "crash course"],                "🐍 Python & Programming"),
        (["blockchain", "bitcoin", "ethereum", "web3", "defi", "crypto", "nft", "satoshi"], "⛓️ Blockchain & Web3"),
        (["data science", "pandas", "numpy", "analytics", "visualization", "storytelling"], "📊 Data Science & Analytics"),
        (["devops", "docker", "kubernetes", "k8s", "terraform", "cicd", "deployment"], "🚀 DevOps & Automation"),
        (["android", "ios", "flutter", "mobile", "react native", "app"],        "📱 Mobile & App Dev"),
        (["math", "maths", "discrete", "linear algebra", "probability", "calculus"], "📐 Mathematics for CS"),
        (["ai", "machine learning", "deep learning", "neural", "superintelligence", "artificial intelligence", "reinforcement"], "🤖 AI & Machine Learning"),
        (["algorithm", "dsa", "clrs", "data structure"],                        "📐 Algorithms & Theory"),
        (["security", "hack", "cyber", "cryptography", "network", "penetration", "exploit"], "🔐 Security & Networking"),
        (["cloud", "distributed", "sre", "reliability", "database", "kubernetes", "terraform"], "☁️ Systems & Cloud"),
        (["web", "javascript", "js", "frontend"],                               "🌐 Web Development"),
        (["startup", "innovation", "strategy", "zero"],                         "💡 Innovation & Strategy"),
        (["science", "cosmos", "future", "space", "philosophy"],                "🔭 Science & Futurism"),
        (["software", "engineering", "clean", "refactor", "pattern", "pragmatic", "domain"], "⚙️ Software Engineering"),
    ]
    for keywords, label in intent_map:
        if any(kw in q or kw in expanded for kw in keywords):
            return label
    return None


def get_search_suggestions(books, partial: str, limit: int = 7) -> list[dict]:
    """
    Real-time autocomplete suggestions for a partial query.
    Returns list of {text, type} dicts.
    """
    if not partial or len(partial) < 2:
        return []

    p = partial.lower()
    results = []
    seen = set()

    # Exact prefix matches first (titles)
    for book in books:
        if book.title.lower().startswith(p):
            key = book.title
            if key not in seen:
                results.append({"text": book.title, "type": "title", "book_id": book.id})
                seen.add(key)

    # Exact prefix matches (authors)
    for book in books:
        if book.author.lower().startswith(p) and len(results) < limit:
            key = f"author:{book.author}"
            if key not in seen:
                results.append({"text": book.author, "type": "author"})
                seen.add(key)

    # Category matches
    cats = set(book.category for book in books)
    for cat in sorted(cats):
        if p in cat.lower() and len(results) < limit:
            key = f"cat:{cat}"
            if key not in seen:
                results.append({"text": cat, "type": "category"})
                seen.add(key)

    # Fuzzy title matches
    if len(results) < limit:
        all_titles = [b.title for b in books]
        fuzzy = difflib.get_close_matches(partial, all_titles, n=4, cutoff=0.35)
        for t in fuzzy:
            if t not in seen and len(results) < limit:
                results.append({"text": t, "type": "fuzzy"})
                seen.add(t)

    # Synonym suggestions
    tokens = re.findall(r'\w+', p)
    for tok in tokens:
        if tok in SYNONYMS and SYNONYMS[tok]:
            for syn in SYNONYMS[tok][:2]:
                if syn not in seen and len(results) < limit:
                    results.append({"text": syn, "type": "related"})
                    seen.add(syn)

    return results[:limit]


# ── Optional Gemini AI natural-language search ─────────────────────────────────
def gemini_interpret_query(query: str, book_titles: list[str]) -> Optional[str]:
    """
    Use Gemini to interpret a natural-language query and return a cleaned search term.
    Only runs if GEMINI_API_KEY is set in environment.
    Returns the interpreted search string, or None on failure/no key.
    """
    api_key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not api_key:
        return None

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')

        titles_sample = '\n'.join(f'- {t}' for t in book_titles[:30])
        prompt = f"""You are a smart library search assistant. Given a user's search query and a list of available book titles, extract the key search intent and return a simple 1-5 word search term that best matches books in the library.

Available books (sample):
{titles_sample}

User query: "{query}"

Return ONLY the search term, nothing else. No explanations, no quotes. Examples:
- "i want something about hacking and security" → cybersecurity hacking
- "books by the clean code author" → Robert Martin
- "that famous algorithms textbook" → Introduction to Algorithms
- "AI books that are available" → artificial intelligence
"""
        response = model.generate_content(prompt)
        interpreted = response.text.strip().strip('"').strip("'")
        if interpreted and len(interpreted) < 80:
            return interpreted
    except Exception:
        pass
    return None
