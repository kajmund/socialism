"""Unit tests for message URL text extraction (no network)."""

from app.llm.message_gen import extract_text_from_html, normalize_url, source_domain


def test_normalize_url_adds_https():
    assert normalize_url("example.com/a") == "https://example.com/a"
    assert normalize_url("https://x.test") == "https://x.test"


def test_source_domain_strips_www():
    assert source_domain("https://www.svt.se/nyheter/x") == "svt.se"


def test_extract_prefers_article_and_meta():
    html = """
    <html>
      <head>
        <title>Sidtitel | Nyhetssajt</title>
        <meta property="og:title" content="Rätt rubrik om vård" />
        <meta property="og:description" content="Ingress om vårdcentralen i Norrköping." />
        <meta name="description" content="Fallback beskrivning" />
      </head>
      <body>
        <nav>Meny Hem Sport Kultur Cookie-banner Acceptera</nav>
        <header>Logga in Prenumerera</header>
        <article>
          <h1>Rätt rubrik om vård</h1>
          <p>Kommunen vill bygga en ny vårdcentral i Eneby.</p>
          <p>Invånarna har väntat i flera år på bättre tillgänglighet.</p>
        </article>
        <footer>Copyright reklam cookies</footer>
      </body>
    </html>
    """
    text = extract_text_from_html(html)
    assert "Rätt rubrik om vård" in text
    assert "Ingress om vårdcentralen" in text
    assert "vårdcentral i Eneby" in text
    assert "Cookie-banner" not in text
    assert "Copyright reklam" not in text


def test_extract_falls_back_when_no_article():
    html = """
    <html><head><title>Plain</title></head>
    <body><p>En kort plaintextsida utan artikel-tagg men med innehåll nog.</p></body></html>
    """
    text = extract_text_from_html(html)
    assert "Titel: Plain" in text
    assert "plaintextsida" in text
